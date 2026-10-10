"""Pure breakdown-label masking (D3.8).

Breakdown labels carry a label class. ``category`` labels are always shown.
``business_name`` and ``person_name`` labels are shown only with the matching
clearance; otherwise the admin-set mode applies:

- ``pseudonymise``: ``"Account 7f3a1c"`` / ``"Person 7f3a1c"``, the first 6 hex
  chars of HMAC-SHA256(key, ``"{label_class}:{label}"``). Stable per key and
  distinct across classes.
- ``suppress``: no rows; ``suppressed_rows`` says how many were hidden.
- ``bucket``: the first ``bucket_size`` rows become ``Top 1..N``; the rest of the
  *fetched* rows are summed into ``Others``. ``others_covers`` documents that the
  sum covers only the fetched rows, not the whole population.

Fail closed: a missing setting, an unknown mode, an unknown label class, a
non-positive bucket size or ``pseudonymise`` with an empty or blank key all degrade to
``suppress`` (logged ``atlas.masking_fallback``). Label values are never logged.

The clearance mapping is duplicated in ``app.access.catalog`` (atlas may not
import access); a test asserts the two agree.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Protocol

import structlog

logger = structlog.get_logger()

CATEGORY: Final = "category"
CLEARANCE_FOR_CLASS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "business_name": "fields:business_names",
        "person_name": "fields:people_names",
    }
)
OTHERS_COVERS: Final = "remaining fetched rows"

PSEUDONYMISE: Final = "pseudonymise"
SUPPRESS: Final = "suppress"
BUCKET: Final = "bucket"

_PREFIX: Final[Mapping[str, str]] = MappingProxyType(
    {"business_name": "Account", "person_name": "Person"}
)
_TOKEN_LEN: Final = 6

Rows = Sequence[Mapping[str, Any]]


class MaskMode(Protocol):
    """Admin-set masking mode for one label class.

    Satisfied structurally by ``access.policy.LabelMode``.
    """

    @property
    def mode(self) -> str: ...

    @property
    def bucket_size(self) -> int: ...


@dataclass(frozen=True, slots=True)
class MaskedBreakdown:
    """Breakdown rows after masking.

    ``applied`` is the effective mode, or ``None`` when rows were left untouched.
    """

    rows: list[dict[str, Any]]
    applied: str | None
    suppressed_rows: int | None = None
    others_covers: str | None = None


def mask_breakdown(
    rows: Rows,
    label_class: str,
    *,
    cleared: bool,
    mode: MaskMode | None,
    key: str,
) -> MaskedBreakdown:
    """Mask breakdown ``rows`` (``{"label", "value"}`` dicts) for one label class."""
    if label_class == CATEGORY:
        return MaskedBreakdown(rows=_copy(rows), applied=None)
    if label_class not in CLEARANCE_FOR_CLASS:
        return _fallback(rows, label_class, "unknown label class")
    if cleared:
        return MaskedBreakdown(rows=_copy(rows), applied=None)
    if mode is None:
        return _fallback(rows, label_class, "no mode configured")
    return _apply(rows, label_class, mode, key)


def _apply(rows: Rows, label_class: str, mode: MaskMode, key: str) -> MaskedBreakdown:
    if mode.mode == PSEUDONYMISE and key.strip():
        return MaskedBreakdown(
            rows=_pseudonymise(rows, label_class, key), applied=PSEUDONYMISE
        )
    if mode.mode == SUPPRESS:
        return _suppress(rows)
    if mode.mode == BUCKET and mode.bucket_size >= 1:
        return _bucket(rows, mode.bucket_size)
    reasons = {
        PSEUDONYMISE: "pseudonym key missing",
        BUCKET: "invalid bucket size",
    }
    return _fallback(rows, label_class, reasons.get(mode.mode, "unknown mode"))


def _copy(rows: Rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def _token(key: str, label_class: str, label: object) -> str:
    message = f"{label_class}:{label}".encode()
    digest = hmac.new(key.encode(), message, hashlib.sha256).hexdigest()
    return digest[:_TOKEN_LEN]


# Masked rows are rebuilt as {label, value} so no extra column passes through.
def _pseudonymise(rows: Rows, label_class: str, key: str) -> list[dict[str, Any]]:
    prefix = _PREFIX[label_class]
    return [
        {
            "label": f"{prefix} {_token(key, label_class, r.get('label'))}",
            "value": r.get("value"),
        }
        for r in rows
    ]


def _suppress(rows: Rows) -> MaskedBreakdown:
    return MaskedBreakdown(rows=[], applied=SUPPRESS, suppressed_rows=len(rows))


def _value(row: Mapping[str, Any]) -> float:
    value = row.get("value")
    return float(value) if value is not None else 0.0


def _bucket(rows: Rows, size: int) -> MaskedBreakdown:
    top = [
        {"label": f"Top {i}", "value": r.get("value")}
        for i, r in enumerate(rows[:size], start=1)
    ]
    rest = rows[size:]
    if not rest:
        return MaskedBreakdown(rows=top, applied=BUCKET)
    others = {"label": "Others", "value": sum(_value(r) for r in rest)}
    return MaskedBreakdown(
        rows=[*top, others], applied=BUCKET, others_covers=OTHERS_COVERS
    )


def _fallback(rows: Rows, label_class: str, reason: str) -> MaskedBreakdown:
    # Never log label values: class, reason and count only.
    logger.warning(
        "atlas.masking_fallback",
        label_class=label_class,
        reason=reason,
        rows=len(rows),
    )
    return _suppress(rows)
