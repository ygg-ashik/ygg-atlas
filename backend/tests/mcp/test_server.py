"""The per-principal MCP server: filtered tools/list, run_tool, factories (D19, D20,
D26, D27, D31). HTTP behaviour end to end is in test_mcp_e2e.py."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select
from structlog.testing import capture_logs

from app.access import PolicyUnavailableError, sync_scope_dimensions
from app.atlas import AtlasTools, get_registry
from app.config import get_settings
from app.identity import TokenKind, User
from app.mcp import TOOL_REQUIREMENTS, build_mcp
from app.mcp import server as mcp_server
from app.mcp.auth import AtlasAccessToken, AtlasTokenVerifier
from app.models.audit import AtlasAuditLog
from tests.access_helpers import (
    add_grant,
    make_user,
    seed_label_classes,
    set_attribute,
)
from tests.identity.credential_helpers import insert_token, make_client
from tests.mcp.oauth_client import RESOURCE

# The published tool contract, as on main before phase 4 (names and descriptions).
PUBLISHED_TOOLS = {
    "list_metrics": "List every governed metric and funnel in the atlas, "
    "with descriptions.",
    "query_metric": "Get a governed metric value. Range metrics need ISO dates; "
    "snapshot metrics don't.",
    "metric_breakdown": "Top-N breakdown of a metric (e.g. top accounts by revenue, "
    "tasks per CSM).",
    "describe_entity": "Describe an atlas entity: fields, PII flags, its metrics "
    "and funnels.",
    "funnel_analyze": "Analyze a governed funnel over a date range: step conversion "
    "and biggest drop-off.",
    "compare_periods": "Compare a metric between two date ranges: values, delta, "
    "percent change.",
    "search_atlas": "Keyword-search the atlas for entities, metrics, and funnels "
    "matching a topic.",
}
MCP_ONLY = {"list_metrics", "search_atlas", "describe_entity"}
METRIC_TOOLS = {"query_metric", "metric_breakdown", "compare_periods"}


async def _user(db: AsyncSession, role: str = "analyst") -> User:
    return await make_user(db, f"u-{uuid4().hex[:8]}@yougotagift.com", role=role)


async def _token(
    db: AsyncSession, user: User, kind: TokenKind = TokenKind.PAT, **row: Any
) -> AtlasAccessToken:
    _, raw = await insert_token(db, user, kind, **row)
    token = await AtlasTokenVerifier(RESOURCE).verify_token(raw)
    assert token is not None
    return token


class SignedIn:
    """Acts as a token, as the SDK's AuthContextMiddleware does for each request."""

    def append(self, token: AtlasAccessToken) -> None:
        auth_context_var.set(AuthenticatedUser(token))


@pytest.fixture
def signed_in() -> Iterator[SignedIn]:
    reset_to = auth_context_var.set(None)
    yield SignedIn()
    auth_context_var.reset(reset_to)


async def _listed() -> set[str]:
    server = build_mcp(get_settings())
    return {tool.name for tool in await server.list_tools()}


# ---- the tool contract -------------------------------------------------------------


async def test_tool_requirements_cover_every_registered_tool() -> None:
    server = build_mcp(get_settings())
    registered = {tool.name for tool in await FastMCP.list_tools(server)}
    assert registered == set(TOOL_REQUIREMENTS)


async def test_tool_names_and_descriptions_are_unchanged() -> None:
    server = build_mcp(get_settings())
    tools = await FastMCP.list_tools(server)
    assert {tool.name: tool.description for tool in tools} == PUBLISHED_TOOLS
    # Unstructured results, as before: no output schema is published.
    assert all(tool.outputSchema is None for tool in tools)


# ---- tools/list (spec §6 point 1) ----------------------------------------------------


async def test_list_tools_without_a_token_is_empty(
    db: AsyncSession, signed_in: SignedIn
) -> None:
    await add_grant(db, await _user(db), "*")
    assert await _listed() == set()


async def test_list_tools_without_mcp_use_is_empty(
    db: AsyncSession, signed_in: SignedIn
) -> None:
    viewer = await _user(db, role="viewer")
    await add_grant(db, viewer, "*")
    signed_in.append(await _token(db, viewer))
    assert await _listed() == set()


async def test_list_tools_shows_everything_the_caller_can_use(
    db: AsyncSession, signed_in: SignedIn
) -> None:
    analyst = await _user(db)
    await add_grant(db, analyst, "*")
    signed_in.append(await _token(db, analyst))
    assert await _listed() == set(TOOL_REQUIREMENTS)


async def test_list_tools_hides_metric_tools_without_visible_metrics(
    db: AsyncSession, signed_in: SignedIn
) -> None:
    analyst = await _user(db)
    await add_grant(db, analyst, "demo/checkout/*")  # a funnel, no metrics
    signed_in.append(await _token(db, analyst))
    assert await _listed() == MCP_ONLY | {"funnel_analyze"}


async def test_list_tools_hides_the_funnel_tool_without_visible_funnels(
    db: AsyncSession, signed_in: SignedIn
) -> None:
    analyst = await _user(db)
    await add_grant(db, analyst, "demo/order/*")  # metrics, no funnel
    signed_in.append(await _token(db, analyst))
    assert await _listed() == MCP_ONLY | METRIC_TOOLS


async def test_list_tools_with_mcp_use_and_no_grants_lists_only_the_catalog_tools(
    db: AsyncSession, signed_in: SignedIn
) -> None:
    signed_in.append(await _token(db, await _user(db)))
    assert await _listed() == MCP_ONLY


@pytest.mark.parametrize(
    "error", [PolicyUnavailableError("down"), RuntimeError("10.0.0.5 refused")]
)
async def test_list_tools_fails_closed_on_policy_errors(
    db: AsyncSession,
    signed_in: SignedIn,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    analyst = await _user(db)
    await add_grant(db, analyst, "*")
    signed_in.append(await _token(db, analyst))

    async def broken(*_args: object) -> None:
        raise error

    monkeypatch.setattr(mcp_server, "policy_for", broken)
    with capture_logs() as logs:
        assert await _listed() == set()
    assert {
        "event": "mcp.list_tools_failed",
        "error": type(error).__name__,
    }.items() <= (logs[-1].items())
    assert "10.0.0.5" not in str(logs)


async def test_a_tool_missing_from_the_table_is_never_listed(
    db: AsyncSession, signed_in: SignedIn
) -> None:
    analyst = await _user(db)
    await add_grant(db, analyst, "*")
    signed_in.append(await _token(db, analyst))
    server = build_mcp(get_settings())

    async def export_everything() -> dict[str, Any]:
        return {}

    server.add_tool(export_everything, name="export_everything")

    listed = {tool.name for tool in await server.list_tools()}
    assert "export_everything" not in listed
    assert listed == set(TOOL_REQUIREMENTS)


# ---- run_tool (D20, D31) -------------------------------------------------------------


async def test_run_tool_without_a_principal_is_unavailable(
    signed_in: SignedIn,
) -> None:
    with capture_logs() as logs:
        result = await mcp_server.run_tool("list_metrics", {})
    assert result == dict(mcp_server.UNAVAILABLE)
    assert logs[-1]["event"] == "mcp.no_principal"


async def test_a_denied_call_logs_the_credential(
    db: AsyncSession, signed_in: SignedIn
) -> None:
    viewer = await _user(db, role="viewer")
    client = await make_client(db)
    token = await _token(
        db,
        viewer,
        TokenKind.OAUTH_ACCESS,
        client_id=client.client_id,
        family_id=uuid4(),
        audience=RESOURCE,
    )
    signed_in.append(token)

    with capture_logs() as logs:
        assert await mcp_server.run_tool("list_metrics", {}) == dict(
            mcp_server.NO_MCP_ACCESS
        )

    (denied,) = [e for e in logs if e["event"] == "mcp.tool_denied"]
    assert denied["tool"] == "list_metrics"
    assert denied["user_id"] == str(viewer.id)
    assert denied["token_id"] == str(token.token_id)
    assert denied["client_id"] == client.client_id


async def test_run_tool_without_mcp_use_is_denied(
    db: AsyncSession, signed_in: SignedIn
) -> None:
    viewer = await _user(db, role="viewer")
    await add_grant(db, viewer, "*")
    signed_in.append(await _token(db, viewer))

    result = await mcp_server.run_tool("list_metrics", {})

    assert result == dict(mcp_server.NO_MCP_ACCESS)
    assert "mcp:use" in result["error"]


async def test_run_tool_runs_as_the_principal_with_its_grants(
    db: AsyncSession, signed_in: SignedIn
) -> None:
    analyst = await _user(db)
    signed_in.append(await _token(db, analyst))
    assert await mcp_server.run_tool("list_metrics", {}) == {"sources": []}

    await add_grant(db, analyst, "demo/order/*")

    result = await mcp_server.run_tool("list_metrics", {})
    assert "revenue" in {m["id"] for m in result["sources"][0]["metrics"]}


async def _boom_policy(*_args: object) -> None:
    raise PolicyUnavailableError("policy store at 10.0.0.5 unreachable")


async def _boom_runtime(*_args: object) -> None:
    raise RuntimeError("OperationalError: connection to 10.0.0.5 refused")


async def _boom_execute(*_args: object) -> None:
    raise RuntimeError("tool exploded near 10.0.0.5")


@pytest.mark.parametrize(
    ("target", "replacement", "error"),
    [
        ("policy_for", _boom_policy, "PolicyUnavailableError"),
        ("policy_for", _boom_runtime, "RuntimeError"),
        ("execute", _boom_execute, "RuntimeError"),
    ],
)
async def test_run_tool_collapses_failures_to_unavailable(
    db: AsyncSession,
    signed_in: SignedIn,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    replacement: object,
    error: str,
) -> None:
    analyst = await _user(db)
    await add_grant(db, analyst, "*")
    signed_in.append(await _token(db, analyst))
    if target == "execute":
        monkeypatch.setattr(AtlasTools, "execute", replacement)
    else:
        monkeypatch.setattr(mcp_server, target, replacement)

    with capture_logs() as logs:
        result = await mcp_server.run_tool("list_metrics", {})

    assert result == dict(mcp_server.UNAVAILABLE)
    assert "10.0.0.5" not in str(result)
    assert "10.0.0.5" not in str(logs)
    assert {"event": "mcp.tool_unavailable", "error": error}.items() <= logs[-1].items()


async def test_run_tool_audits_the_credential(
    db: AsyncSession, signed_in: SignedIn
) -> None:
    analyst = await _user(db)
    await add_grant(db, analyst, "*")
    client = await make_client(db)
    token = await _token(
        db,
        analyst,
        TokenKind.OAUTH_ACCESS,
        client_id=client.client_id,
        family_id=uuid4(),
        audience=RESOURCE,
    )
    signed_in.append(token)

    await mcp_server.run_tool("list_metrics", {})

    row = (
        await db.execute(
            select(AtlasAuditLog).where(col(AtlasAuditLog.user_id) == analyst.id)
        )
    ).scalar_one()
    assert row.surface == "mcp"
    assert row.auth_method == "oauth"
    assert row.token_id == token.token_id
    assert row.client_id == client.client_id
    assert row.tool == "list_metrics"


async def test_run_tool_applies_row_scope_and_masking_like_chat(
    db: AsyncSession, signed_in: SignedIn
) -> None:
    """The phase 3/4 seam: a PAT call is scoped and masked, and audited with both."""
    await sync_scope_dimensions(db, get_registry().scope_catalog())
    await seed_label_classes(db, person="suppress")
    rep = await _user(db)
    await add_grant(db, rep, "demo/order/*", row_scope={"sales_rep": ["$self"]})
    await set_attribute(db, rep, "rep_name", "Aisha Khan")
    token = await _token(db, rep)
    signed_in.append(token)
    today = datetime.now(UTC).date()
    week = {
        "start_date": (today - timedelta(days=7)).isoformat(),
        "end_date": (today - timedelta(days=1)).isoformat(),
    }

    result = await mcp_server.run_tool(
        "metric_breakdown", {"metric_id": "orders_by_rep", "limit": 10, **week}
    )

    assert "error" not in result, result
    assert result["rows"] == []
    assert result["suppressed_rows"] == 1  # only their own row, and uncleared
    provenance = result["provenance"][0]
    assert provenance["scope"] == {"restricted": True, "dimensions": ["sales_rep"]}
    assert provenance["masking"] == {"label_class": "person_name", "mode": "suppress"}
    assert "Aisha" not in repr(result)
    row = (
        await db.execute(
            select(AtlasAuditLog).where(col(AtlasAuditLog.user_id) == rep.id)
        )
    ).scalar_one()
    assert (row.surface, row.tool, row.token_id) == (
        "mcp",
        "metric_breakdown",
        token.token_id,
    )
    assert row.scope is not None
    assert row.scope["restricted"] is True
    assert row.masking is not None
    assert row.masking["label_class"] == "person_name"
    assert row.masking["mode"] == "suppress"


# ---- factories (D26, D27) ------------------------------------------------------------


def test_transport_security_from_public_url() -> None:
    local = mcp_server.transport_security_for("http://localhost:8080")
    assert set(local.allowed_hosts) == {
        "localhost:8080",
        "localhost",
        "127.0.0.1",
        "localhost:*",
        "127.0.0.1:*",
        "[::1]:*",
    }
    assert "http://localhost:8080" in local.allowed_origins
    assert local.enable_dns_rebinding_protection

    public = mcp_server.transport_security_for("https://atlas.example.com")
    assert {"atlas.example.com", "localhost:*"} <= set(public.allowed_hosts)
    assert "https://atlas.example.com" in public.allowed_origins
    assert not any("evil" in host for host in public.allowed_hosts)

    ported = mcp_server.transport_security_for("https://atlas.example.com:8443")
    assert {"atlas.example.com:8443", "atlas.example.com"} <= set(ported.allowed_hosts)
    assert "https://atlas.example.com:8443" in ported.allowed_origins


def test_build_mcp_uses_the_configured_urls() -> None:
    public = "https://atlas.example.com"
    settings = get_settings().model_copy(update={"atlas_public_url": public})

    server = build_mcp(settings)

    auth = server.settings.auth
    assert auth is not None
    assert str(auth.issuer_url) == f"{public}/mcp-server"
    assert str(auth.resource_server_url) == f"{public}/mcp-server/mcp"
    assert auth.validate_token_resource is True
    assert server.settings.stateless_http is True
    security = server.settings.transport_security
    assert security is not None
    assert "atlas.example.com" in security.allowed_hosts


def test_each_build_is_a_fresh_server() -> None:
    first, second = build_mcp(get_settings()), build_mcp(get_settings())
    assert first is not second
    assert first.atlas_verifier is not second.atlas_verifier


def test_standalone_mode_serves_on_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, dict[str, Any]]] = []

    def run(app: object, **kwargs: Any) -> None:
        calls.append((app, kwargs))

    monkeypatch.setattr(mcp_server.uvicorn, "run", run)
    mcp_server.serve_standalone()
    [(app, kwargs)] = calls
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8090
    assert hasattr(app, "routes")
