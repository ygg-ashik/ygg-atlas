"""Types shared by every provider tool loop and its caller.

Events are SSE-ready JSON dicts (see the package docstring for their shapes).
"""

from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

type Event = dict[str, Any]
type ExecuteTool = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class Toolset:
    """The tools offered to the model, paired with the function that runs them.

    `schemas` are Anthropic-style (`name`, `description`, `input_schema`);
    providers convert them to their native format.
    """

    schemas: Sequence[dict[str, Any]]
    execute: ExecuteTool


class ToolLoopRunner(Protocol):
    """A provider loop with its client already bound."""

    def __call__(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        toolset: Toolset,
        max_rounds: int,
    ) -> AsyncGenerator[Event, None]: ...
