"""Keyset cursors from a request: a bad one is a 422, never a 500."""

from datetime import datetime
from typing import Final
from uuid import UUID

from app.access.cursor import InvalidCursorError, decode_cursor, decode_time_cursor
from app.access.errors import InvalidChangeError

BAD_CURSOR: Final = "That page link is invalid; reload the list."


def page_position(cursor: str | None) -> tuple[datetime, UUID] | None:
    """A request's cursor as a UTC keyset position; a bad one is a 422 (P5-D16)."""
    if cursor is None:
        return None
    try:
        return decode_time_cursor(cursor)
    except InvalidCursorError:
        raise InvalidChangeError(BAD_CURSOR) from None


def email_position(cursor: str | None) -> tuple[str, UUID] | None:
    """A user-list cursor as an (email, id) keyset position; a bad one is a 422."""
    if cursor is None:
        return None
    try:
        return decode_cursor(cursor)
    except InvalidCursorError:
        raise InvalidChangeError(BAD_CURSOR) from None
