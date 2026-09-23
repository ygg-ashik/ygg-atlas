"""Anthropic Messages API tool loop (streaming)."""

import json
from collections.abc import AsyncGenerator, Awaitable, Callable

from app.atlas import ATLAS_TOOL_SCHEMAS

BUDGET_ERROR = "The assistant hit its tool budget for this question. Try a narrower question."


async def run_tool_loop(
    client,
    model: str,
    system: str,
    messages: list[dict],
    execute_tool: Callable[[str, dict], Awaitable[dict]],
    max_rounds: int,
) -> AsyncGenerator[dict, None]:
    messages = list(messages)
    final_text_parts: list[str] = []
    usage_totals = {"input_tokens": 0, "output_tokens": 0}

    for _round in range(max_rounds):
        async with client.messages.stream(
            model=model,
            max_tokens=2048,
            system=system,
            messages=messages,
            tools=ATLAS_TOOL_SCHEMAS,
        ) as stream:
            async for event in stream:
                if (
                    event.type == "content_block_delta"
                    and getattr(event.delta, "type", "") == "text_delta"
                ):
                    final_text_parts.append(event.delta.text)
                    yield {"type": "token", "content": event.delta.text}
            response = await stream.get_final_message()

        usage_totals["input_tokens"] += response.usage.input_tokens
        usage_totals["output_tokens"] += response.usage.output_tokens

        if response.stop_reason != "tool_use":
            yield {
                "type": "final",
                "content": "".join(final_text_parts),
                "token_usage": usage_totals,
            }
            return

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            yield {"type": "tool_status", "tool": block.name}
            result = await execute_tool(block.name, dict(block.input))
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    yield {"type": "error", "message": BUDGET_ERROR}
