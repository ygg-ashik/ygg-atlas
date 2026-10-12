"""Date arguments of the range tools, as inclusive UTC bounds."""

from datetime import UTC, date, datetime
from datetime import time as dt_time
from typing import Any

from app.atlas.tools.errors import AtlasToolError


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise AtlasToolError(
            f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}"
        ) from None


def range_params(start: str, end: str) -> dict[str, Any]:
    """Inclusive UTC datetime bounds: [start 00:00:00, end 23:59:59.999999]."""
    start_d = _parse_date(start, "start_date")
    end_d = _parse_date(end, "end_date")
    if end_d < start_d:
        raise AtlasToolError("end_date must be on or after start_date")
    return {
        "start": datetime.combine(start_d, dt_time.min, tzinfo=UTC),
        "end": datetime.combine(end_d, dt_time.max, tzinfo=UTC),
    }
