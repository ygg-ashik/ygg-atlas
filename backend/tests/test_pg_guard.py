"""Unit tests for the opt-in Postgres test guard (tests/pg_guard.py)."""

import pytest

from tests.pg_guard import is_disposable


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql+asyncpg://atlas:atlas@localhost:5432/scratch", True),
        ("postgresql+asyncpg://atlas:atlas@localhost:5432/atlas_test", True),
        ("postgresql+asyncpg://atlas:atlas@localhost:5432/test-db", True),
        ("postgresql+asyncpg://atlas:atlas@localhost:5432/atlas_latest", False),
        ("postgresql+asyncpg://atlas:atlas@localhost:5432/contest_prod", False),
        ("postgresql+asyncpg://atlas:atlas@localhost:5432/ygg_atlas", False),
        ("postgresql+asyncpg://atlas:atlas@localhost:5432/", False),
        ("not a url at all", False),
        ("", False),
    ],
)
def test_is_disposable(url: str, expected: bool) -> None:
    assert is_disposable(url) is expected
