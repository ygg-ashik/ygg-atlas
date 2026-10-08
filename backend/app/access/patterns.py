"""Resource paths and grant patterns (spec §2).

A resource path is `source/entity/item` (an entity itself is `source/entity`).
A pattern with a trailing `*` matches that prefix itself and everything under
it: `demo/order/*` matches `demo/order` and `demo/order/revenue`; `demo/*`
matches `demo`, `demo/order` and `demo/order/revenue`; a lone `*` matches
everything. A pattern without a trailing `*` must be a full item path of
exactly three segments (a mid-pattern `*` still matches exactly one segment,
e.g. `demo/*/revenue`) — shorter paths like `demo` or `demo/order` name an
entity or source and are rejected in favor of the trailing-`*` form, which
fails closed: it never leaves anything under a denied path reachable.
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
    if segments[-1] != "*" and len(segments) != MAX_SEGMENTS:
        msg = (
            f"'{pattern}' names an entity or source; use '{pattern}/*' to "
            "cover it and everything under it."
        )
        raise InvalidPatternError(msg)
    return pattern


def matches(pattern: str, path: str) -> bool:
    """True if `path` is covered by `pattern`.

    Both arguments must already be well formed: run `validate_pattern` on a
    pattern before storing it; resource paths always come from the registry.
    """
    if not path:
        return False
    want = pattern.split("/")
    have = path.split("/")
    if want[-1] == "*":
        prefix = want[:-1]
        return len(have) >= len(prefix) and _same(prefix, have)
    return len(want) == len(have) and _same(want, have)


def _same(pattern: list[str], path: list[str]) -> bool:
    return all(p in ("*", s) for p, s in zip(pattern, path, strict=False))
