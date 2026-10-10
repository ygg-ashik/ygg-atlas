"""Pure breakdown-label masking (D3.8): modes, clearances, fail-closed fallbacks."""

import hashlib
import hmac
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from structlog.testing import capture_logs

from app.atlas.masking import (
    CLEARANCE_FOR_CLASS,
    OTHERS_COVERS,
    MaskedBreakdown,
    mask_breakdown,
)

KEY = "test-pseudonym-key"


@dataclass(frozen=True)
class Mode:
    mode: str
    bucket_size: int = 5


def _rows(*pairs: tuple[str, float]) -> list[dict[str, Any]]:
    return [{"label": label, "value": value} for label, value in pairs]


FIVE = _rows(
    ("Alice", 50.0), ("Bob", 40.0), ("Carol", 30.0), ("Dan", 20.0), ("Eve", 10.0)
)


def _fallbacks(
    logs: Sequence[MutableMapping[str, Any]],
) -> list[MutableMapping[str, Any]]:
    return [e for e in logs if e["event"] == "atlas.masking_fallback"]


def test_category_is_never_masked() -> None:
    rows = _rows(("b2c", 10.0), ("b2b", 5.0))
    out = mask_breakdown(rows, "category", cleared=False, mode=None, key="")
    assert out == MaskedBreakdown(rows=rows, applied=None)
    assert "category" not in CLEARANCE_FOR_CLASS


@pytest.mark.parametrize("label_class", ["business_name", "person_name"])
def test_cleared_rows_are_untouched(label_class: str) -> None:
    out = mask_breakdown(
        FIVE, label_class, cleared=True, mode=Mode("suppress"), key=KEY
    )
    assert out.applied is None
    assert out.rows == FIVE
    assert out.suppressed_rows is None


def test_masked_output_is_a_copy() -> None:
    rows = _rows(("Alice", 1.0))
    out = mask_breakdown(rows, "person_name", cleared=True, mode=None, key=KEY)
    out.rows[0]["label"] = "changed"
    assert rows[0]["label"] == "Alice"


def test_clearance_mapping() -> None:
    assert dict(CLEARANCE_FOR_CLASS) == {
        "business_name": "fields:business_names",
        "person_name": "fields:people_names",
    }


def test_pseudonymise_is_stable_and_keyed() -> None:
    mode = Mode("pseudonymise")
    first = mask_breakdown(FIVE, "person_name", cleared=False, mode=mode, key=KEY)
    again = mask_breakdown(FIVE, "person_name", cleared=False, mode=mode, key=KEY)
    other_key = mask_breakdown(
        FIVE, "person_name", cleared=False, mode=mode, key="other"
    )
    business = mask_breakdown(FIVE, "business_name", cleared=False, mode=mode, key=KEY)

    assert first.applied == "pseudonymise"
    assert first.rows == again.rows
    labels = [r["label"] for r in first.rows]
    assert all(
        label.startswith("Person ") and len(label) == len("Person ") + 6
        for label in labels
    )
    assert len(set(labels)) == len(labels)
    assert "Alice" not in labels
    assert [r["value"] for r in first.rows] == [r["value"] for r in FIVE]
    assert labels != [r["label"] for r in other_key.rows]
    business_labels = [r["label"] for r in business.rows]
    assert all(label.startswith("Account ") for label in business_labels)
    # Same label, two classes: different tokens.
    assert [lbl.split(" ")[1] for lbl in labels] != [
        lbl.split(" ")[1] for lbl in business_labels
    ]


def test_pseudonymise_matches_the_documented_hmac() -> None:
    out = mask_breakdown(
        _rows(("Alice", 1.0)),
        "person_name",
        cleared=False,
        mode=Mode("pseudonymise"),
        key=KEY,
    )
    token = hmac.new(KEY.encode(), b"person_name:Alice", hashlib.sha256).hexdigest()[:6]
    assert out.rows[0]["label"] == f"Person {token}"


def test_pseudonymise_without_a_key_suppresses() -> None:
    with capture_logs() as logs:
        out = mask_breakdown(
            FIVE, "person_name", cleared=False, mode=Mode("pseudonymise"), key=""
        )
    assert out.applied == "suppress"
    assert out.rows == []
    assert out.suppressed_rows == 5
    events = _fallbacks(logs)
    assert len(events) == 1
    assert "Alice" not in repr(events)


def test_suppress_drops_rows_and_counts_them() -> None:
    out = mask_breakdown(
        FIVE[:3], "business_name", cleared=False, mode=Mode("suppress"), key=KEY
    )
    assert out.applied == "suppress"
    assert out.rows == []
    assert out.suppressed_rows == 3
    assert out.others_covers is None


def test_bucket_ranks_and_sums_the_rest() -> None:
    out = mask_breakdown(
        FIVE, "person_name", cleared=False, mode=Mode("bucket", 2), key=KEY
    )
    assert out.applied == "bucket"
    assert out.rows == [
        {"label": "Top 1", "value": 50.0},
        {"label": "Top 2", "value": 40.0},
        {"label": "Others", "value": 60.0},
    ]
    assert out.others_covers == OTHERS_COVERS == "remaining fetched rows"
    assert out.suppressed_rows is None


def test_bucket_with_fewer_rows_than_the_size() -> None:
    out = mask_breakdown(
        FIVE[:2], "person_name", cleared=False, mode=Mode("bucket", 5), key=KEY
    )
    assert out.rows == [
        {"label": "Top 1", "value": 50.0},
        {"label": "Top 2", "value": 40.0},
    ]
    assert out.others_covers is None


def test_bucket_treats_missing_values_as_zero() -> None:
    rows = [
        *FIVE[:1],
        {"label": "Bob", "value": None},
        {"label": "Carol", "value": 3.0},
    ]
    out = mask_breakdown(
        rows, "person_name", cleared=False, mode=Mode("bucket", 1), key=KEY
    )
    assert out.rows[-1] == {"label": "Others", "value": 3.0}


@pytest.mark.parametrize("bucket_size", [0, -1])
def test_bucket_with_an_invalid_size_suppresses(bucket_size: int) -> None:
    with capture_logs() as logs:
        out = mask_breakdown(
            FIVE,
            "person_name",
            cleared=False,
            mode=Mode("bucket", bucket_size),
            key=KEY,
        )
    assert out.applied == "suppress"
    assert out.rows == []
    assert len(_fallbacks(logs)) == 1


@pytest.mark.parametrize("mode", [None, Mode("shred"), Mode("")])
def test_unknown_mode_or_missing_setting_suppresses(mode: Mode | None) -> None:
    with capture_logs() as logs:
        out = mask_breakdown(FIVE, "business_name", cleared=False, mode=mode, key=KEY)
    assert out.applied == "suppress"
    assert out.rows == []
    assert out.suppressed_rows == 5
    events = _fallbacks(logs)
    assert len(events) == 1
    assert events[0]["label_class"] == "business_name"
    assert "Alice" not in repr(events)


def test_unknown_label_class_is_suppressed_even_when_cleared() -> None:
    with capture_logs() as logs:
        out = mask_breakdown(
            FIVE, "email", cleared=True, mode=Mode("pseudonymise"), key=KEY
        )
    assert out.applied == "suppress"
    assert out.rows == []
    assert len(_fallbacks(logs)) == 1


@pytest.mark.parametrize("mode", [Mode("pseudonymise"), Mode("bucket", 1)])
def test_masked_rows_carry_only_label_and_value(mode: Mode) -> None:
    rows = [
        {"label": "Alice", "value": 2.0, "email": "alice@example.com"},
        {"label": "Bob", "value": 1.0, "email": "bob@example.com"},
    ]
    out = mask_breakdown(rows, "person_name", cleared=False, mode=mode, key=KEY)
    assert out.rows
    assert all(set(r) == {"label", "value"} for r in out.rows)
    assert "alice@example.com" not in repr(out.rows)


@pytest.mark.parametrize("key", [" ", "\t\n"])
def test_pseudonymise_with_a_blank_key_suppresses(key: str) -> None:
    with capture_logs() as logs:
        out = mask_breakdown(
            FIVE, "person_name", cleared=False, mode=Mode("pseudonymise"), key=key
        )
    assert out.applied == "suppress"
    assert out.rows == []
    assert len(_fallbacks(logs)) == 1
