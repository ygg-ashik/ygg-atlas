"""One audit row per tool execution, allowed or denied, with scope and masking.

The call trace collects what a call touched (the compiled row scope, the
applied label masking) while the tool runs; the audit row is written from it.
"""

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.atlas.policy import AtlasCaller
from app.atlas.scope import CompiledScope
from app.atlas.tools.errors import DENIED_KEY, AtlasAccessDeniedError, AtlasToolError
from app.models.audit import AtlasAuditLog
from app.sources import ConnectorError, ConnectorNotConfiguredError

logger = structlog.get_logger()

ALLOW = "allow"
DENY = "deny"
MAX_DENY_REASON = 200
UNKNOWN_TOOL = "unknown tool"

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class CallTrace:
    """What one execute() call touched, for its audit row.

    `scope`: None when no query ran, else the concrete compiled alternatives.
    `masking`: None, or the applied label masking (class and mode, row counts;
    never label values).
    """

    scope: dict[str, Any] | None = None
    masking: dict[str, Any] | None = None


# Per execute() call; a ContextVar so concurrent calls never share a trace.
CALL_TRACE: ContextVar[CallTrace | None] = ContextVar("atlas_call_trace", default=None)


@dataclass(frozen=True, slots=True)
class Outcome:
    success: bool = True
    error: str | None = None
    decision: str = ALLOW
    deny_reason: str | None = None


def audit_scope(compiled: CompiledScope) -> dict[str, Any]:
    if not compiled.restricted:
        return {"restricted": False}
    return {
        "restricted": True,
        "alternatives": [
            {dim: sorted(values) for dim, values in sorted(alternative.items())}
            for alternative in compiled.alternatives
        ],
    }


def record_scope(compiled: CompiledScope) -> None:
    """Record a compiled row scope on the current call's trace."""
    trace = CALL_TRACE.get()
    if trace is not None:
        trace.scope = audit_scope(compiled)


def record_masking(masking: dict[str, Any]) -> None:
    """Record applied label masking on the current call's trace."""
    trace = CALL_TRACE.get()
    if trace is not None:
        trace.masking = masking


async def run_tool(
    caller: AtlasCaller,
    tool: str,
    handler: ToolHandler,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], Outcome]:
    """Run one handler; every failure becomes an `{"error": ...}` result."""
    outcome = Outcome()
    result: dict[str, Any]
    try:
        result = await handler(**arguments)
    except AtlasAccessDeniedError as exc:
        outcome = Outcome(False, str(exc), DENY, exc.reason[:MAX_DENY_REASON])
        result = {"error": str(exc)}
        if exc.resource is not None:
            # Chat-only: the agent loop turns it into a `denied` block and
            # strips it, as MCP does; models never see it.
            result[DENIED_KEY] = {"resource": exc.resource, "label": exc.label}
    except (AtlasToolError, ConnectorNotConfiguredError, ConnectorError) as exc:
        outcome = Outcome(False, str(exc))
        result = {"error": str(exc)}
    except TypeError as exc:
        outcome = Outcome(False, f"Invalid arguments: {exc}")
        result = {"error": f"Invalid arguments: {exc}"}
    except Exception as exc:  # unexpected — log loudly, keep the answer honest
        logger.exception(
            "atlas.tool_failed",
            tool=tool,
            user_id=str(caller.user_id),
            session_id=str(caller.session_id),
        )
        # Raw errors can echo bound scope values, so the audit row and the
        # answer carry none (the class name carries no values). Driver
        # errors in the log are value-free via hide_parameters.
        error = f"Internal error executing {tool}"
        outcome = Outcome(False, f"{error} ({type(exc).__name__})")
        result = {"error": error}
    return result, outcome


async def write_audit(
    db: AsyncSession | None,
    caller: AtlasCaller,
    tool: str,
    arguments: dict[str, Any],
    outcome: Outcome,
    duration_ms: int,
) -> None:
    if db is None:
        return
    trace = CALL_TRACE.get()
    db.add(
        AtlasAuditLog(
            user_uid=str(caller.user_id),
            user_id=caller.user_id,
            auth_method=caller.auth_method,
            session_id=caller.session_id,
            surface=caller.surface,
            tool=tool,
            arguments=arguments,
            success=outcome.success,
            error=outcome.error,
            duration_ms=duration_ms,
            decision=outcome.decision,
            deny_reason=outcome.deny_reason,
            scope=trace.scope if trace else None,
            masking=trace.masking if trace else None,
            token_id=caller.token_id,
            client_id=caller.client_id,
        )
    )
    await db.commit()
