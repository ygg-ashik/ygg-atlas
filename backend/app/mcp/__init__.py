"""MCP: the per-principal MCP server, its OAuth authorization server and discovery
documents, and the credential API. Other modules import only from here."""

from app.mcp.access_log import install_access_log_redaction
from app.mcp.oauth_routes import discovery_router
from app.mcp.router import mcp_router
from app.mcp.server import (
    TOOL_REQUIREMENTS,
    AtlasMCP,
    build_http_app,
    build_mcp,
    prepare_mcp_auth,
)

__all__ = [
    "TOOL_REQUIREMENTS",
    "AtlasMCP",
    "build_http_app",
    "build_mcp",
    "discovery_router",
    "install_access_log_redaction",
    "mcp_router",
    "prepare_mcp_auth",
]
