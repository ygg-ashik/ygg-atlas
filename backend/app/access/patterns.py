"""Resource paths and grant patterns (spec §2).

A resource path is `source/entity/item` (an entity itself is `source/entity`).
Pattern segments are literal or `*`. A trailing `*` matches one or more remaining
segments, so `deepsales/*` covers every entity and item in DeepSales; a `*` in
the middle matches exactly one segment.
"""

import re

_SEGMENT = re.compile(r"[a-z0-9_]+")
MAX_SEGMENTS = 3


class InvalidPatternError(ValueError):
    """A grant target that is not a resource pattern."""


def validate_pattern(pattern: str) -> str:
    segments = pattern.split("/")
    if not 1 <= len(segments) <= MAX_SEGMENTS or any(
        s != "*" and not _SEGMENT.fullmatch(s) for s in segments
    ):
        msg = (
            f"'{pattern}' is not a resource pattern. Use paths like '*', "
            "'deepsales/*' or 'demo/order/revenue'."
        )
        raise InvalidPatternError(msg)
    return pattern


def matches(pattern: str, path: str) -> bool:
    want = pattern.split("/")
    have = path.split("/")
    if want[-1] == "*":
        prefix = want[:-1]
        return len(have) > len(prefix) and _same(prefix, have)
    return len(want) == len(have) and _same(want, have)


def _same(pattern: list[str], path: list[str]) -> bool:
    return all(p in ("*", s) for p, s in zip(pattern, path, strict=False))
