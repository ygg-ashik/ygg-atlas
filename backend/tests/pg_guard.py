"""Shared guard for the opt-in, real-Postgres test modules.

Both test_alembic_postgres.py and test_access_postgres.py run DROP SCHEMA public
CASCADE against TEST_PG_URL, so a misconfigured env var must never let that land on
a real database. A plain substring check is not enough ("atlas_latest" contains
neither word as a whole token, but "contest_prod" does contain "test" as a
substring) -- this splits the database name into tokens first.
"""

import re

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

_DISPOSABLE_TOKENS = frozenset({"test", "scratch"})


def is_disposable(url: str) -> bool:
    """True only when the URL parses and its database name has a "test" or
    "scratch" token (split on `_`, `-`, `.`), never from a bare substring match."""
    if not url:
        return False
    try:
        database = make_url(url).database or ""
    except ArgumentError:
        return False
    tokens = re.split(r"[_\-.]", database.lower())
    return any(token in _DISPOSABLE_TOKENS for token in tokens)
