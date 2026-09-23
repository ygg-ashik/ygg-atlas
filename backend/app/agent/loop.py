"""Chat turn orchestration: guardrails → provider tool loop → SSE events.

Yields SSE-ready event dicts:
  {type: 'token', content}      streamed text delta
  {type: 'tool_status', tool}   a tool is being executed
  {type: 'done', content, provenance, model, token_usage}
  {type: 'blocked', reason}     guardrail rejection
  {type: 'error', message}

The LLM provider (Anthropic or OpenAI) is selected from which API key is
configured; see Settings.llm_provider.
"""

from collections.abc import AsyncGenerator
from uuid import UUID

import structlog

from app.agent.guardrails import check_input
from app.agent.prompts import build_system_prompt
from app.agent.providers import anthropic_loop, openai_loop
from app.atlas import AtlasTools
from app.config import get_settings

logger = structlog.get_logger()


def _history_to_messages(history: list[dict]) -> list[dict]:
    """Prior turns as plain text messages (tool exchanges are not replayed)."""
    return [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if m.get("content") and m["role"] in ("user", "assistant")
    ]


def _select_provider(client):
    """Returns (provider_module, client). An injected client implies Anthropic (tests)."""
    settings = get_settings()
    if client is not None:
        return anthropic_loop, client
    if settings.llm_provider == "openai":
        from openai import AsyncOpenAI

        return openai_loop, AsyncOpenAI(api_key=settings.openai_api_key)
    from anthropic import AsyncAnthropic

    return anthropic_loop, AsyncAnthropic(api_key=settings.anthropic_api_key)


async def run_chat_turn(
    user_uid: str,
    session_id: UUID,
    content: str,
    history: list[dict],
    db,
    client=None,
) -> AsyncGenerator[dict, None]:
    settings = get_settings()

    verdict = await check_input(content, user_uid, db)
    if not verdict.allowed:
        yield {"type": "blocked", "reason": verdict.reason}
        return

    provider, client = _select_provider(client)
    tools = AtlasTools(user_uid=user_uid, surface="chat", session_id=session_id, db=db)
    provenance: list[dict] = []

    async def execute_tool(name: str, arguments: dict) -> dict:
        result = await tools.execute(name, arguments)
        if isinstance(result, dict) and result.get("provenance"):
            provenance.extend(result["provenance"])
        return result

    messages = _history_to_messages(history) + [{"role": "user", "content": content}]
    model = settings.resolved_agent_model

    try:
        async for event in provider.run_tool_loop(
            client=client,
            model=model,
            system=build_system_prompt(),
            messages=messages,
            execute_tool=execute_tool,
            max_rounds=settings.agent_max_tool_rounds,
        ):
            if event["type"] == "final":
                yield {
                    "type": "done",
                    "content": event["content"],
                    "provenance": provenance,
                    "model": model,
                    "token_usage": event["token_usage"],
                }
            else:
                yield event
    except Exception:
        logger.exception("agent.turn_failed", session_id=str(session_id))
        yield {"type": "error", "message": "Something went wrong answering that. Please retry."}
