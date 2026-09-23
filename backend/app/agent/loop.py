"""Thin Claude tool-calling loop.

Yields SSE-ready event dicts:
  {type: 'token', content}      streamed text delta
  {type: 'tool_status', tool}   a tool is being executed
  {type: 'done', content, provenance, model, token_usage}
  {type: 'blocked', reason}     guardrail rejection
  {type: 'error', message}
"""

import json
from collections.abc import AsyncGenerator
from uuid import UUID

import structlog
from anthropic import AsyncAnthropic

from app.agent.guardrails import check_input
from app.agent.prompts import build_system_prompt
from app.atlas import ATLAS_TOOL_SCHEMAS, AtlasTools
from app.config import get_settings

logger = structlog.get_logger()


def _client() -> AsyncAnthropic:
    return AsyncAnthropic(api_key=get_settings().anthropic_api_key)


def _history_to_messages(history: list[dict]) -> list[dict]:
    """Prior turns as plain text messages (tool exchanges are not replayed)."""
    return [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if m.get("content") and m["role"] in ("user", "assistant")
    ]


async def run_chat_turn(
    user_uid: str,
    session_id: UUID,
    content: str,
    history: list[dict],
    db,
    client: AsyncAnthropic | None = None,
) -> AsyncGenerator[dict, None]:
    settings = get_settings()

    verdict = await check_input(content, user_uid, db)
    if not verdict.allowed:
        yield {"type": "blocked", "reason": verdict.reason}
        return

    client = client or _client()
    tools = AtlasTools(user_uid=user_uid, surface="chat", session_id=session_id, db=db)

    messages = _history_to_messages(history) + [{"role": "user", "content": content}]
    provenance: list[dict] = []
    final_text_parts: list[str] = []
    usage_totals = {"input_tokens": 0, "output_tokens": 0}

    try:
        for _round in range(settings.agent_max_tool_rounds):
            round_text_parts: list[str] = []
            async with client.messages.stream(
                model=settings.agent_model,
                max_tokens=2048,
                system=build_system_prompt(),
                messages=messages,
                tools=ATLAS_TOOL_SCHEMAS,
            ) as stream:
                async for event in stream:
                    if (
                        event.type == "content_block_delta"
                        and getattr(event.delta, "type", "") == "text_delta"
                    ):
                        round_text_parts.append(event.delta.text)
                        yield {"type": "token", "content": event.delta.text}
                response = await stream.get_final_message()

            usage_totals["input_tokens"] += response.usage.input_tokens
            usage_totals["output_tokens"] += response.usage.output_tokens
            final_text_parts.extend(round_text_parts)

            if response.stop_reason != "tool_use":
                break

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                yield {"type": "tool_status", "tool": block.name}
                result = await tools.execute(block.name, dict(block.input))
                if isinstance(result, dict) and result.get("provenance"):
                    provenance.extend(result["provenance"])
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    }
                )
            messages.append({"role": "user", "content": tool_results})
        else:
            yield {
                "type": "error",
                "message": "The assistant hit its tool budget for this question. "
                "Try a narrower question.",
            }
            return

        yield {
            "type": "done",
            "content": "".join(final_text_parts),
            "provenance": provenance,
            "model": settings.agent_model,
            "token_usage": usage_totals,
        }
    except Exception:
        logger.exception("agent.turn_failed", session_id=str(session_id))
        yield {"type": "error", "message": "Something went wrong answering that. Please retry."}
