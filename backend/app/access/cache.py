"""Per-process Policy cache keyed by (user_id, policy_version) (spec §8).

Every access write bumps policy_version, so a new version simply misses. An entry
also expires when the earliest grant it used expires (no bump happens then).
"""

from collections import OrderedDict
from datetime import datetime
from uuid import UUID

from app.access.policy import Policy

DEFAULT_MAX_ENTRIES = 1024


class PolicyCache:
    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._entries: OrderedDict[tuple[UUID, int], Policy] = OrderedDict()
        self._max = max_entries

    def get(self, user_id: UUID, version: int, now: datetime) -> Policy | None:
        key = (user_id, version)
        policy = self._entries.get(key)
        if policy is None:
            return None
        if policy.valid_until is not None and policy.valid_until <= now:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return policy

    def put(self, policy: Policy) -> None:
        key = (policy.user_id, policy.policy_version)
        self._entries[key] = policy
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()


_shared = PolicyCache()


def shared_cache() -> PolicyCache:
    """The process-wide cache used by every request."""
    return _shared
