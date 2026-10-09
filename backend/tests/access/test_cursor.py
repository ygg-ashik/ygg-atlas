"""The keyset cursor: an opaque, URL-safe page link that decodes strictly."""

import base64
import re
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.access.cursor import (
    MAX_CURSOR_LENGTH,
    InvalidCursorError,
    decode_cursor,
    decode_time_cursor,
    encode_cursor,
    encode_time_cursor,
    time_page,
)
from app.access.schemas import Page

ROW_ID = UUID("6f1c2d3e-4b5a-4c6d-8e9f-0a1b2c3d4e5f")


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_round_trips_a_key_and_id() -> None:
    row_id = uuid4()
    assert decode_cursor(encode_cursor("sara@x.com", row_id)) == ("sara@x.com", row_id)


def test_key_may_contain_the_separator() -> None:
    assert decode_cursor(encode_cursor("a|b|c", ROW_ID)) == ("a|b|c", ROW_ID)


def test_time_cursor_round_trips_an_aware_datetime() -> None:
    at = datetime(2026, 10, 9, 12, 30, 15, 123456, tzinfo=UTC)
    decoded_at, decoded_id = decode_time_cursor(encode_cursor(at.isoformat(), ROW_ID))
    assert decoded_at == at
    assert decoded_at.tzinfo is not None
    assert decoded_id == ROW_ID


def test_time_cursor_keeps_a_non_utc_offset_aware() -> None:
    at = datetime(2026, 10, 9, 16, 30, tzinfo=timezone(timedelta(hours=4)))
    decoded_at, _ = decode_time_cursor(encode_cursor(at.isoformat(), ROW_ID))
    assert decoded_at == at
    assert decoded_at.tzinfo == UTC


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("", id="empty"),
        pytest.param("!!!", id="not-base64-alphabet"),
        pytest.param("a+b/" + _b64(f"k|{ROW_ID}"), id="standard-alphabet-chars"),
        pytest.param(_b64(f"k|{ROW_ID}") + "==", id="padding"),
        pytest.param(_b64(f"k|{ROW_ID}") + "=", id="stray-padding"),
        pytest.param(_b64(f"k|{ROW_ID}") + " ", id="trailing-space"),
        pytest.param(_b64(f"k|{ROW_ID}")[:-1], id="truncated"),
        pytest.param(_b64(f"no-separator-{ROW_ID}"), id="no-separator"),
        pytest.param(_b64("k|not-a-uuid"), id="bad-uuid"),
        pytest.param(_b64(f"k|{ROW_ID.hex}"), id="uuid-without-hyphens"),
        pytest.param(_b64(f"k|{{{ROW_ID}}}"), id="uuid-with-braces"),
        pytest.param(_b64(f"k|urn:uuid:{ROW_ID}"), id="uuid-urn"),
        pytest.param(_b64(f"|{ROW_ID}"), id="empty-key"),
        pytest.param(
            base64.urlsafe_b64encode(b"\xff\xfe|" + str(ROW_ID).encode())
            .decode()
            .rstrip("="),
            id="not-utf8",
        ),
        pytest.param("A" * (MAX_CURSOR_LENGTH + 1), id="over-long"),
    ],
)
def test_garbage_is_rejected(raw: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(raw)


def test_a_cursor_at_the_length_cap_still_decodes() -> None:
    key = "k" * 347  # 347 + 37 bytes = 384 bytes = exactly 512 base64 characters
    raw = encode_cursor(key, ROW_ID)
    assert len(raw) == MAX_CURSOR_LENGTH
    assert decode_cursor(raw) == (key, ROW_ID)


def test_naive_time_cursor_is_rejected() -> None:
    with pytest.raises(InvalidCursorError):
        decode_time_cursor(encode_cursor("2026-10-09T12:30:00", ROW_ID))


def test_non_iso_time_cursor_is_rejected() -> None:
    with pytest.raises(InvalidCursorError):
        decode_time_cursor(encode_cursor("yesterday", ROW_ID))


def test_invalid_cursor_error_is_a_value_error() -> None:
    assert issubclass(InvalidCursorError, ValueError)


def test_cursor_is_url_safe() -> None:
    raw = encode_cursor("ünïcode+/?&=|key", ROW_ID)
    assert re.fullmatch(r"[A-Za-z0-9_-]+", raw)


def test_page_defaults_to_the_last_page() -> None:
    page = Page[int](items=[1, 2])
    assert page.next_cursor is None
    assert page.model_dump() == {"items": [1, 2], "next_cursor": None}


def test_naive_time_is_encoded_as_utc() -> None:
    aware = datetime(2026, 10, 9, 12, 30, tzinfo=UTC)
    naive = aware.replace(tzinfo=None)  # as SQLite returns it
    at, row_id = decode_time_cursor(encode_time_cursor(naive, ROW_ID))
    assert at == aware
    assert row_id == ROW_ID


def _rows(n: int) -> list[tuple[datetime, UUID]]:
    start = datetime(2026, 10, 9, tzinfo=UTC)
    return [(start - timedelta(minutes=i), uuid4()) for i in range(n)]


def test_time_page_with_a_spare_row_links_the_next_page() -> None:
    rows = _rows(3)
    page, cursor = time_page(rows, 2, lambda r: r)
    assert page == rows[:2]
    assert cursor is not None
    assert decode_time_cursor(cursor) == rows[1]


@pytest.mark.parametrize("n", [0, 1, 2])
def test_time_page_without_a_spare_row_is_the_last(n: int) -> None:
    rows = _rows(n)
    assert time_page(rows, 2, lambda r: r) == (rows, None)
