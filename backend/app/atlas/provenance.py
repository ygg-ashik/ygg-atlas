"""Provenance objects attached to every number the platform returns."""

from datetime import UTC, datetime
from typing import Any


def build_provenance(  # noqa: PLR0913  # one flat record; fields are keyword-only
    tool: str,
    source: str,
    *,
    metric_id: str | None = None,
    metric_name: str | None = None,
    freshness: str | None = None,
    scope: dict[str, Any] | None = None,
    masking: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`scope` names restricted dimensions only, never their values (D3.11);
    `masking` is the applied label masking, or `None` when labels are shown."""
    return {
        "tool": tool,
        "source": source,
        "metric_id": metric_id,
        "metric_name": metric_name,
        "freshness": freshness,
        "executed_at": datetime.now(UTC).isoformat(),
        "scope": scope,
        "masking": masking,
    }
