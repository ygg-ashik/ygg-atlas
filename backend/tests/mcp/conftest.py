"""Every MCP test starts with empty process-wide rate limiters: the OAuth routes
and the MCP app are limited per source, and xdist runs many tests per process."""

from collections.abc import Iterator

import pytest

from app.mcp.ratelimit import reset_limiters


@pytest.fixture(autouse=True)
def _fresh_rate_limits() -> Iterator[None]:
    reset_limiters()
    yield
    reset_limiters()
