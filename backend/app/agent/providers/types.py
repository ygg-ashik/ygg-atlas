"""Types shared by every provider tool loop and its caller.

Events are SSE-ready JSON dicts (see the package docstring for their shapes).
"""

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, Protocol

type Event = dict[str, Any]
type ExecuteTool = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class ToolLoopRunner(Protocol):
    """A provider loop with its client already bound."""

    def __call__(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        execute_tool: ExecuteTool,
        max_rounds: int,
    ) -> AsyncGenerator[Event, None]: ...
