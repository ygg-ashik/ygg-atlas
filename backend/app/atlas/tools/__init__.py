"""The seven atlas tools — the ONLY way agents access business data.

Consumed in-process by the chat agent and exposed verbatim over MCP.
Every execution is audited. Every numeric result carries provenance.

`get_connector` is re-exported as the one seam the tool families read
connectors through (see `door.connector`).
"""

from app.atlas.tools.errors import (
    DENIED_KEY,
    POLICY_FAILED,
    AtlasAccessDeniedError,
    AtlasPolicyError,
    AtlasToolError,
    without_denial,
)
from app.atlas.tools.executor import AtlasTools
from app.atlas.tools.schemas import ATLAS_TOOL_SCHEMAS
from app.sources import get_connector

__all__ = [
    "ATLAS_TOOL_SCHEMAS",
    "DENIED_KEY",
    "POLICY_FAILED",
    "AtlasAccessDeniedError",
    "AtlasPolicyError",
    "AtlasToolError",
    "AtlasTools",
    "get_connector",
    "without_denial",
]
