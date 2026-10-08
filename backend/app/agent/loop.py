"""Chat turn orchestration: guardrails -> provider tool loop -> SSE events.

Yields SSE-ready event dicts:
  {type: 'token', content}      streamed text delta
  {type: 'tool_status', tool}   a tool is being executed
  {type: 'done', content, provenance, blocks, model, token_usage}
  {type: 'blocked', reason}     guardrail rejection
  {type: 'error', message}

The LLM provider (Anthropic or OpenAI) is selected from which API key is
configured; see Settings.llm_provider.

`blocks` are structured answer parts (see app.agent.blocks): at most one
clarify block from the `ask_clarification` control tool, plus one artifact
block per table-shaped atlas tool result.
"""

from collections.abc import AsyncGenerator
from functools import partial
from typing import Any
from uuid import UUID

import structlog
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.blocks import CLARIFY_TOOL, artifact_from_result, build_clarify_block
from app.agent.guardrails import check_input
from app.agent.prompts import build_system_prompt
from app.agent.providers import anthropic_loop, openai_loop
from app.agent.providers.anthropic_loop import AnthropicClient
from app.agent.providers.types import Event, ToolLoopRunner, Toolset
from app.atlas import ATLAS_TOOL_SCHEMAS, AtlasTools
from app.config import get_settings

logger = structlog.get_logger()


def _history_to_messages(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prior turns as plain text messages (tool exchanges are not replayed)."""
    return [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if m.get("content") and m["role"] in ("user", "assistant")
    ]


CLARIFY_SHOWN = {
    "status": "shown_to_user",
    "instruction": "End your turn with one short sentence.",
}
CLARIFY_INVALID = {"error": "Provide a question and 2-4 options with non-empty labels."}


class _TurnRecorder:
    """Runs one turn's tools and records the provenance and blocks they produce."""

    def __init__(self, tools: AtlasTools) -> None:
        self._tools = tools
        self.provenance: list[dict[str, Any]] = []
        self.blocks: list[dict[str, Any]] = []
        self._artifact_seq = 0

    def toolset(self) -> Toolset:
        return Toolset([*ATLAS_TOOL_SCHEMAS, CLARIFY_TOOL], self.execute)

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == CLARIFY_TOOL["name"]:
            return self._clarify(arguments)
        result = await self._tools.execute(name, arguments)
        self.provenance.extend(result.get("provenance") or [])
        artifact = artifact_from_result(name, result, seq=self._artifact_seq + 1)
        if artifact is not None:
            self._artifact_seq += 1
            self.blocks.append(artifact)
        return result

    def _clarify(self, arguments: dict[str, Any]) -> dict[str, Any]:
        # Control tool: no data access, so not an atlas execution and not audited.
        block = build_clarify_block(arguments, set(self._tools.registry.metrics))
        if block is None:
            return dict(CLARIFY_INVALID)
        if not any(b["kind"] == "clarify" for b in self.blocks):
            self.blocks.append(block)
        return dict(CLARIFY_SHOWN)


def _select_provider(client: AnthropicClient | None) -> ToolLoopRunner:
    """The provider loop bound to its client.

    An injected client implies Anthropic (tests).
    """
    settings = get_settings()
    if client is not None:
        return partial(anthropic_loop.run_tool_loop, client)
    if settings.llm_provider == "openai":
        return partial(
            openai_loop.run_tool_loop, AsyncOpenAI(api_key=settings.openai_api_key)
        )
    return partial(
        anthropic_loop.run_tool_loop,
        AsyncAnthropic(api_key=settings.anthropic_api_key),
    )


async def run_chat_turn(
    user_uid: str,
    session_id: UUID,
    content: str,
    history: list[dict[str, Any]],
    db: AsyncSession,
    client: AnthropicClient | None = None,
) -> AsyncGenerator[Event, None]:
    settings = get_settings()

    verdict = await check_input(content, user_uid, db)
    if not verdict.allowed:
        yield {"type": "blocked", "reason": verdict.reason}
        return

    run_tool_loop = _select_provider(client)
    tools = AtlasTools(user_uid=user_uid, surface="chat", session_id=session_id, db=db)
    recorder = _TurnRecorder(tools)

    messages = [*_history_to_messages(history), {"role": "user", "content": content}]
    model = settings.resolved_agent_model

    try:
        async for event in run_tool_loop(
            model=model,
            system=build_system_prompt(),
            messages=messages,
            toolset=recorder.toolset(),
            max_rounds=settings.agent_max_tool_rounds,
        ):
            if event["type"] == "final":
                yield {
                    "type": "done",
                    "content": event["content"],
                    "provenance": recorder.provenance,
                    "blocks": recorder.blocks,
                    "model": model,
                    "token_usage": event["token_usage"],
                }
            else:
                yield event
    except Exception:
        logger.exception("agent.turn_failed", session_id=str(session_id))
        yield {
            "type": "error",
            "message": "Something went wrong answering that. Please retry.",
        }
