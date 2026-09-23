"""Provenance objects attached to every number the platform returns."""

from datetime import UTC, datetime


def build_provenance(
    tool: str,
    source: str,
    metric_id: str | None = None,
    metric_name: str | None = None,
    freshness: str | None = None,
) -> dict:
    return {
        "tool": tool,
        "source": source,
        "metric_id": metric_id,
        "metric_name": metric_name,
        "freshness": freshness,
        "executed_at": datetime.now(UTC).isoformat(),
    }
