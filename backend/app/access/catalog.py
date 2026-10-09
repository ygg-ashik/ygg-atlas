"""Capabilities and roles (spec §5.1).

Code is the source of truth; the DB mirrors it.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

CHAT_USE: Final = "chat:use"
MCP_USE: Final = "mcp:use"
TOKENS_CREATE: Final = "tokens:create"
EXPORT_DATA: Final = "export:data"
SANDBOX_RUN: Final = "sandbox:run"
ALERTS_MANAGE: Final = "alerts:manage"
SCHEDULES_MANAGE: Final = "schedules:manage"
ANALYSES_SAVE: Final = "analyses:save"
ADMIN_USERS: Final = "admin:users"
ADMIN_GROUPS: Final = "admin:groups"
ADMIN_AUDIT: Final = "admin:audit"
ADMIN_TOKENS: Final = "admin:tokens"
ADMIN_CLIENTS: Final = "admin:clients"

CAPABILITIES: Final[Mapping[str, str]] = MappingProxyType(
    {
        CHAT_USE: "Use the atlas web chat and dashboard",
        MCP_USE: "Connect MCP clients such as Claude Code, claude.ai or Claude Desktop",
        TOKENS_CREATE: "Create personal access tokens",
        EXPORT_DATA: "Export results as files",
        SANDBOX_RUN: "Run analyses in the sandbox",
        ALERTS_MANAGE: "Create and manage alerts",
        SCHEDULES_MANAGE: "Create and manage schedules",
        ANALYSES_SAVE: "Save analyses for reuse",
        ADMIN_USERS: "Manage users, roles, status and direct grants",
        ADMIN_GROUPS: "Manage groups, members and group grants",
        ADMIN_AUDIT: "Read the audit and access-change logs",
        ADMIN_TOKENS: "Manage everyone's tokens",
        ADMIN_CLIENTS: "Manage connected OAuth clients",
    }
)

CLEARANCE_BUSINESS_NAMES: Final = "fields:business_names"
CLEARANCE_PEOPLE_NAMES: Final = "fields:people_names"

# Field clearances (spec §5.6): a breakdown label class is shown in clear only
# with the matching clearance. The atlas keeps the same label class ->
# clearance mapping in app/atlas/masking.py; a test asserts they agree.
CLEARANCES: Final[Mapping[str, str]] = MappingProxyType(
    {
        CLEARANCE_BUSINESS_NAMES: "See customer and business names in breakdowns",
        CLEARANCE_PEOPLE_NAMES: (
            "See the names of people, such as account managers, in breakdowns"
        ),
    }
)

# Ascending: each role includes everything below it.
ROLES: Final[tuple[str, ...]] = ("viewer", "analyst", "builder", "admin")

_ADDS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "viewer": frozenset({CHAT_USE}),
        "analyst": frozenset({MCP_USE, TOKENS_CREATE, EXPORT_DATA, SANDBOX_RUN}),
        "builder": frozenset({ALERTS_MANAGE, SCHEDULES_MANAGE, ANALYSES_SAVE}),
        "admin": frozenset(
            {ADMIN_USERS, ADMIN_GROUPS, ADMIN_AUDIT, ADMIN_TOKENS, ADMIN_CLIENTS}
        ),
    }
)


def _cumulative_bundles() -> dict[str, frozenset[str]]:
    bundles: dict[str, frozenset[str]] = {}
    running: set[str] = set()
    for name in ROLES:
        running |= _ADDS[name]
        bundles[name] = frozenset(running)
    return bundles


_BUNDLES: Final[Mapping[str, frozenset[str]]] = MappingProxyType(_cumulative_bundles())


def role_capabilities(role: str) -> frozenset[str]:
    """The role's cumulative bundle. An unknown role grants nothing (fail closed)."""
    return _BUNDLES.get(role, frozenset())
