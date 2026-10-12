"""Optional equality filters shared by the list queries."""

from typing import Any

from sqlalchemy import ColumnElement
from sqlalchemy.orm import Mapped


def equal_where(*filters: tuple[Mapped[Any], object]) -> list[ColumnElement[bool]]:
    """`column == value` for every filter that was given (None = not filtered)."""
    return [column == value for column, value in filters if value is not None]
