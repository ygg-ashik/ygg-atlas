"""Generic keyset cursor for paged lists (pure; imports nothing from app.access).

A cursor is base64url, without padding, of ``"<key>|<uuid>"``: the sort key of the
last row on a page and that row's id as the tie-breaker. Decoding is strict, so only
a cursor this server could have issued is accepted. A cursor never widens access:
every paged query still filters by tenant, so a forged cursor only positions a page.
"""

import base64
import binascii
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

MAX_CURSOR_LENGTH: Final = 512
_SEPARATOR: Final = "|"
_URL_SAFE: Final = re.compile(r"[A-Za-z0-9_-]+")


class InvalidCursorError(ValueError):
    """A cursor that is not one this server issued. Mapped to 422 by the caller."""


def encode_cursor(key: str, row_id: UUID) -> str:
    raw = f"{key}{_SEPARATOR}{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(raw: str) -> tuple[str, UUID]:
    """Return ``(key, row_id)``; raise `InvalidCursorError` for anything else."""
    if len(raw) > MAX_CURSOR_LENGTH or not _URL_SAFE.fullmatch(raw):
        raise InvalidCursorError("cursor is not base64url text")
    try:
        data = base64.b64decode(
            raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True
        )
        text = data.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise InvalidCursorError("cursor does not decode") from exc
    if base64.urlsafe_b64encode(data).decode("ascii").rstrip("=") != raw:
        raise InvalidCursorError("cursor is not canonical")
    key, separator, id_text = text.rpartition(_SEPARATOR)
    if not separator or not key:
        raise InvalidCursorError("cursor has no key")
    try:
        row_id = UUID(id_text)
    except ValueError as exc:
        raise InvalidCursorError("cursor has no row id") from exc
    if str(row_id) != id_text:  # only the canonical form encode_cursor writes
        raise InvalidCursorError("cursor row id is not canonical")
    return key, row_id


def decode_time_cursor(raw: str) -> tuple[datetime, UUID]:
    """Decode a cursor whose key is a timezone-aware ISO-8601 datetime."""
    key, row_id = decode_cursor(raw)
    try:
        at = datetime.fromisoformat(key)
    except ValueError as exc:
        raise InvalidCursorError("cursor time is not ISO-8601") from exc
    if at.utcoffset() is None:
        raise InvalidCursorError("cursor time has no timezone")
    return at.astimezone(UTC), row_id


def encode_time_cursor(at: datetime, row_id: UUID) -> str:
    """Encode a time key; a naive time is stored UTC (SQLite returns those)."""
    moment = at if at.tzinfo is not None else at.replace(tzinfo=UTC)
    return encode_cursor(moment.isoformat(), row_id)


def time_page[R](
    rows: Sequence[R], limit: int, key: Callable[[R], tuple[datetime, UUID]]
) -> tuple[list[R], str | None]:
    """Split a ``limit + 1`` keyset fetch into one page and the next cursor
    (None on the last page). `key` gives a row's ``(time, id)`` sort key."""
    page = list(rows[:limit])
    if len(rows) <= limit:
        return page, None
    return page, encode_time_cursor(*key(page[-1]))
