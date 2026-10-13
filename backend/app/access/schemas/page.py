"""Keyset paging: one page of any listed shape."""

from pydantic import BaseModel


class Page[T](BaseModel):
    """One page of a keyset-paged list; `next_cursor` is None on the last page."""

    items: list[T]
    next_cursor: str | None = None
