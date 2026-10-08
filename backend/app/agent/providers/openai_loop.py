"""OpenAI Chat Completions tool loop (streaming)."""

import json
from collections.abc import AsyncGenerator, AsyncIterable, Iterable
from typing import Any, Literal, Protocol

from openai.types.chat import ChatCompletionStreamOptionsParam

from app.agent.providers.types import Event, ExecuteTool
from app.atlas import ATLAS_TOOL_SCHEMAS

BUDGET_ERROR = (
    "The assistant hit its tool budget for this question. Try a narrower question."
)

OPENAI_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in ATLAS_TOOL_SCHEMAS
]


class OpenAICompletions(Protocol):
    async def create(
        self,
        *,
        model: str,
        messages: Iterable[Any],
        tools: Iterable[Any],
        stream: Literal[True],
        stream_options: ChatCompletionStreamOptionsParam,
    ) -> AsyncIterable[Any]: ...  # SDK ChatCompletionChunk stream


class OpenAIChat(Protocol):
    @property
    def completions(self) -> OpenAICompletions: ...


class OpenAIClient(Protocol):
    """Structural view of `openai.AsyncOpenAI` (fakeable in tests)."""

    @property
    def chat(self) -> OpenAIChat: ...


def _parse_args(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw) if raw else {}
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _merge_tool_call_deltas(
    tool_calls: dict[int, dict[str, str]],
    deltas: Iterable[Any],  # SDK ChoiceDeltaToolCall
) -> None:
    """Accumulate streamed tool-call fragments into per-index slots."""
    for tc in deltas:
        slot = tool_calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
        if tc.id:
            slot["id"] = tc.id
        if tc.function:
            slot["name"] = slot["name"] or (tc.function.name or "")
            slot["arguments"] += tc.function.arguments or ""


def _assistant_tool_message(
    round_text_parts: list[str], ordered: list[dict[str, str]]
) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": "".join(round_text_parts) or None,
        "tool_calls": [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"] or "{}",
                },
            }
            for tc in ordered
        ],
    }


async def run_tool_loop(
    client: OpenAIClient,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    execute_tool: ExecuteTool,
    max_rounds: int,
) -> AsyncGenerator[Event, None]:
    messages = [{"role": "system", "content": system}, *messages]
    final_text_parts: list[str] = []
    usage_totals = {"input_tokens": 0, "output_tokens": 0}

    for _round in range(max_rounds):
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=OPENAI_TOOL_SCHEMAS,
            stream=True,
            stream_options={"include_usage": True},
        )

        round_text_parts: list[str] = []
        tool_calls: dict[int, dict[str, str]] = {}  # index -> {id, name, arguments}
        finish_reason = None
        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                usage_totals["input_tokens"] += usage.prompt_tokens or 0
                usage_totals["output_tokens"] += usage.completion_tokens or 0
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            finish_reason = choice.finish_reason or finish_reason
            delta = choice.delta
            if delta is None:
                continue
            if delta.content:
                round_text_parts.append(delta.content)
                yield {"type": "token", "content": delta.content}
            _merge_tool_call_deltas(tool_calls, delta.tool_calls or [])

        final_text_parts.extend(round_text_parts)

        if finish_reason != "tool_calls" or not tool_calls:
            yield {
                "type": "final",
                "content": "".join(final_text_parts),
                "token_usage": usage_totals,
            }
            return

        ordered = [tool_calls[i] for i in sorted(tool_calls)]
        messages.append(_assistant_tool_message(round_text_parts, ordered))
        for tc in ordered:
            yield {"type": "tool_status", "tool": tc["name"]}
            result = await execute_tool(tc["name"], _parse_args(tc["arguments"]))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, default=str),
                }
            )

    yield {"type": "error", "message": BUDGET_ERROR}
