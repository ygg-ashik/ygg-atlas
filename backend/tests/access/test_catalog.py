from itertools import pairwise

from app.access.catalog import (
    ADMIN_GROUPS,
    CAPABILITIES,
    CHAT_USE,
    MCP_USE,
    ROLES,
    role_capabilities,
)


def test_roles_are_cumulative() -> None:
    bundles = [role_capabilities(role) for role in ROLES]
    for lower, higher in pairwise(bundles):
        assert lower < higher


def test_viewer_can_only_chat() -> None:
    assert role_capabilities("viewer") == {CHAT_USE}


def test_mcp_starts_at_analyst_and_admin_actions_at_admin() -> None:
    assert MCP_USE not in role_capabilities("viewer")
    assert MCP_USE in role_capabilities("analyst")
    assert ADMIN_GROUPS not in role_capabilities("builder")
    assert ADMIN_GROUPS in role_capabilities("admin")


def test_unknown_role_grants_nothing() -> None:
    assert role_capabilities("superuser") == frozenset()


def test_every_capability_is_described_and_reachable() -> None:
    assert all(CAPABILITIES.values())
    assert set(CAPABILITIES) == role_capabilities("admin")
