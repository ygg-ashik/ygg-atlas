"""Anthropic Messages API tool loop (streaming)."""

import json
from collections.abc import AsyncGenerator, AsyncIterator, Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from app.agent.providers.types import Event, Toolset

BUDGET_ERROR = (
    "The assistant hit its tool budget for this question. Try a narrower question."
)


class AnthropicUsage(Protocol):
    @property
    def input_tokens(self) -> int: ...

    @property
    def output_tokens(self) -> int: ...


class AnthropicFinalMessage(Protocol):
    @property
    def stop_reason(self) -> str | None: ...

    @property
    def usage(self) -> AnthropicUsage: ...

    @property
    def content(self) -> Sequence[Any]: ...  # SDK content-block union


class AnthropicMessageStream(Protocol):
    """The parts of the SDK's message stream this loop uses."""

    def __aiter__(self) -> AsyncIterator[Any]: ...  # SDK stream-event union

    async def get_final_message(self) -> AnthropicFinalMessage: ...


class AnthropicMessages(Protocol):
    def stream(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: Iterable[Any],
        tools: Iterable[Any],
    ) -> AbstractAsyncContextManager[AnthropicMessageStream]: ...


class AnthropicClient(Protocol):
    """Structural view of `anthropic.AsyncAnthropic` (fakeable in tests)."""

    @property
    def messages(self) -> AnthropicMessages: ...


async def run_tool_loop(
    client: AnthropicClient,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    toolset: Toolset,
    max_rounds: int,
) -> AsyncGenerator[Event, None]:
    messages = list(messages)
    final_text_parts: list[str] = []
    usage_totals = {"input_tokens": 0, "output_tokens": 0}

    for _round in range(max_rounds):
        async with client.messages.stream(
            model=model,
            max_tokens=2048,
            system=system,
            messages=messages,
            tools=toolset.schemas,
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
        tool_results: list[dict[str, Any]] = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            yield {"type": "tool_status", "tool": block.name}
            result = await toolset.execute(block.name, dict(block.input))
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    yield {"type": "error", "message": BUDGET_ERROR}
