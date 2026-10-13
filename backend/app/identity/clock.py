"""The UTC clock every credential service defaults to, and the stored-moment fix."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(moment: datetime) -> datetime:
    """SQLite drops tzinfo on the way back; every stored moment is UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
