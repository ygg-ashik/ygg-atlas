from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.access.cache import PolicyCache
from app.access.policy import Policy

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def _policy(version: int = 1, valid_until: datetime | None = None) -> Policy:
    return Policy(
        user_id=uuid4(),
        tenant="ygg",
        role="viewer",
        active=True,
        policy_version=version,
        valid_until=valid_until,
    )


def test_hit_only_for_the_same_version() -> None:
    cache = PolicyCache()
    policy = _policy(version=3)
    cache.put(policy)
    assert cache.get(policy.user_id, 3, NOW) is policy
    assert cache.get(policy.user_id, 4, NOW) is None


def test_entries_expire_with_their_grants() -> None:
    cache = PolicyCache()
    policy = _policy(valid_until=NOW + timedelta(minutes=5))
    cache.put(policy)
    assert cache.get(policy.user_id, 1, NOW) is policy
    assert cache.get(policy.user_id, 1, NOW + timedelta(minutes=5)) is None


def test_least_recently_used_entries_are_evicted() -> None:
    cache = PolicyCache(max_entries=2)
    first, second, third = _policy(), _policy(), _policy()
    cache.put(first)
    cache.put(second)
    assert cache.get(first.user_id, 1, NOW) is first  # first is now most recent
    cache.put(third)
    assert cache.get(second.user_id, 1, NOW) is None
    assert cache.get(first.user_id, 1, NOW) is first
