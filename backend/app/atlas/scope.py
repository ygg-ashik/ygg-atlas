"""Row-scope compiler: a caller's row scope becomes a bound SQL predicate (D3.1).

Pure: no I/O, no registry, no policy import. The only text this module writes
into SQL is fixed punctuation, generated bind names (``scope_{i}_{j}``) and the
column text from the ``columns`` mapping, which comes from vetted plugin YAML
(linted at load) and is re-validated here. Grant dimension keys are only ever
dict lookups; values only ever travel as bind parameters.

``{{scope}}`` compiles to ``AND TRUE`` when the caller sees all rows, or to
``AND ((col IN (:scope_0_0, :scope_0_1)) OR ((c2 IN (:scope_1_0)) AND ...))``:
alternatives are ORed, dimensions inside one alternative are ANDed.
"""

import re
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

type ScopeAlternative = Mapping[str, frozenset[str]]  # dimension -> values, ANDed
type RowScope = tuple[ScopeAlternative, ...]  # ORed; () never means all rows

SCOPE_TOKEN: Final = "{{scope}}"  # noqa: S105  # SQL template token, not a secret
MAX_SCOPE_VALUES: Final = 100  # per dimension per alternative
MAX_SCOPE_ALTERNATIVES: Final = 50
MAX_SCOPE_BINDS: Final = 1000  # per compiled predicate
UNDECLARED: Final = "scope names a dimension this data does not have"

_UNRESTRICTED: Final = "AND TRUE"
RESERVED_BIND_PREFIX: Final = ":scope_"  # reserved for generated bind names
# Column text spliced into vetted SQL: an identifier, optionally table-qualified.
# Use with ``fullmatch``; the registry lints YAML columns with the same pattern.
COLUMN_PATTERN: Final = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)?")
# A ``:scope_`` bind, but not a Postgres cast such as ``x::scope_enum``.
_RESERVED_BIND: Final = re.compile(r"(?<!:):scope_")


def uses_reserved_bind(sql: str) -> bool:
    """True if ``sql`` names a bind in the prefix reserved for compiled scopes."""
    return _RESERVED_BIND.search(sql) is not None


# The placement lint reads SQL as pieces: (kind, text, paren depth).
type _Piece = tuple[str, str, int]

_SET_OPERATORS: Final = frozenset({"UNION", "INTERSECT", "EXCEPT"})
# Top-level keywords that open a clause; the token must sit in the WHERE clause.
_CLAUSES: Final = frozenset(
    {"SELECT", "FROM", "JOIN", "ON", "USING", "WHERE", "GROUP", "HAVING", "WINDOW"}
    | {"ORDER", "LIMIT", "OFFSET", "FETCH"}
)
# What may follow the token at the top level: another condition, or a clause.
_AFTER_TOKEN: Final = frozenset(
    {"AND", "GROUP", "HAVING", "WINDOW", "ORDER", "LIMIT", "OFFSET", "FETCH"}
)
# Words whose top-level AND/OR rebinds the token: wrap them in parentheses.
_TOP_LEVEL_UNSAFE: Final = {
    "OR": "AND binds tighter than OR",
    "BETWEEN": "its AND would take the scope as a bound",
}
_WORD: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
# Comments, backslashes, dollar quotes and statement separators stop the read.
_STOP: Final = re.compile(r"--|/\*|[\\$;]")
_ALWAYS_UNSAFE: Final = {
    "unterminated": "an unterminated quoted string",
    "prefixed": "a prefixed string literal (E'', U&'' and the like)",
    "--": "an SQL comment (-- or /*)",
    "/*": "an SQL comment (-- or /*)",
    "stop": "a backslash, dollar quote or statement separator",
    "unbalanced": "unbalanced parentheses",
    "nested": f"{SCOPE_TOKEN} inside parentheses",
    "misplaced": (
        f"{SCOPE_TOKEN} not at the top level of the WHERE clause, followed by "
        "AND, a later clause or the end"
    ),
}


def scope_placement_error(sql: str) -> str | None:
    """Why ``{{scope}}`` cannot be safely spliced into ``sql``, or None if it can.

    The token becomes ``AND (...)``, which binds tighter than ``OR`` and looser
    than ``IS`` or ``=``, and can be commented out, quoted or bypassed by a set
    operation. So a scoped query may have no comments, prefixed strings,
    backslashes, dollar quotes, ``;``, UNION/INTERSECT/EXCEPT, or OR or BETWEEN
    outside parentheses, and its parentheses must balance. Every token must sit at the
    top level of the WHERE clause, outside quotes, followed only by AND, a later
    clause or the end of the query. Anything this reader cannot classify fails.
    """
    pieces = list(_pieces(sql))
    checks = (*pieces, *_placement(pieces))
    return next((reason for piece in checks if (reason := _unsafe(*piece))), None)


def _placement(pieces: list[_Piece]) -> Iterator[_Piece]:
    """Unbalanced parentheses, and each token outside its one safe position."""
    if sum(1 if p[1] == "(" else -1 if p[1] == ")" else 0 for p in pieces):
        yield "unbalanced", "", 0
    clause = ""
    for index, (kind, text, depth) in enumerate(pieces):
        if kind == "word" and depth == 0 and text in _CLAUSES:
            clause = text
        if kind != "token":
            continue
        following = next((p for p in pieces[index + 1 :] if p[0] != "token"), None)
        if depth:
            yield "nested", text, depth
        elif clause != "WHERE" or (
            following is not None
            and (following[0] != "word" or following[1] not in _AFTER_TOKEN)
        ):
            yield "misplaced", text, depth


def _unsafe(kind: str, text: str, depth: int) -> str | None:
    if kind in _ALWAYS_UNSAFE:
        return _ALWAYS_UNSAFE[kind]
    if kind == "quoted":
        return f"{SCOPE_TOKEN} inside a quoted string" if SCOPE_TOKEN in text else None
    if text in _SET_OPERATORS:
        return f"{text} (a set operation escapes the scope)"
    if text in _TOP_LEVEL_UNSAFE and depth == 0:
        return f"{text} outside parentheses ({_TOP_LEVEL_UNSAFE[text]})"
    return None


def _quoted(sql: str, i: int) -> tuple[str, str, int]:
    """(kind, text, next index) for the quoted string starting at ``sql[i]``."""
    if i and (sql[i - 1].isalnum() or sql[i - 1] in "_&"):
        return "prefixed", sql[i], len(sql)
    end = sql.find(sql[i], i + 1)
    if end < 0:
        return "unterminated", sql[i:], len(sql)
    return "quoted", sql[i:end], end + 1  # '' reads as two adjacent strings


def _pieces(sql: str) -> Iterator[_Piece]:
    """Quoted strings, tokens, upper-cased words and punctuation, in order.

    Reading stops at the first piece it cannot classify safely (a comment, a
    prefixed or unterminated string, a backslash, ``$``, ``;`` or a ``)`` with
    nothing open), which is reported as that piece.
    """
    depth = 0
    i = 0
    while i < len(sql):
        char = sql[i]
        if char in "'\"":
            kind, text, i = _quoted(sql, i)
            yield kind, text, depth
        elif stop := _STOP.match(sql, i):
            yield (stop.group() if stop.group() in _ALWAYS_UNSAFE else "stop"), "", 0
            return
        elif sql.startswith(SCOPE_TOKEN, i):
            yield "token", SCOPE_TOKEN, depth
            i += len(SCOPE_TOKEN)
        elif word := _WORD.match(sql, i):
            yield "word", word.group().upper(), depth
            i = word.end()
        else:
            depth -= char == ")"
            if depth < 0:
                yield "unbalanced", char, depth
                return
            if not char.isspace():
                yield "punct", char, depth
            depth += char == "("
            i += 1


class ScopeCompileError(ValueError):
    """The scope cannot be compiled safely; the caller must deny the query."""


@dataclass(frozen=True, slots=True)
class CompiledScope:
    sql: str
    params: dict[str, str]
    restricted: bool
    dimensions: tuple[str, ...]
    alternatives: RowScope


def narrow_scope(scope: RowScope | None, columns: Mapping[str, str]) -> RowScope | None:
    """Drop alternatives naming a dimension the entity does not declare (D3.7).

    ``None`` (all rows) passes through. An empty scope, or one that narrows to
    nothing, raises: it must never be read as "no restriction".
    """
    if scope is None:
        return None
    if not scope:
        raise ScopeCompileError("an empty row scope grants no rows")
    if len(scope) > MAX_SCOPE_ALTERNATIVES:
        raise ScopeCompileError(
            f"a row scope has more than {MAX_SCOPE_ALTERNATIVES} alternatives"
        )
    frozen = tuple(_freeze(alt) for alt in scope)
    kept = tuple(alt for alt in frozen if all(dim in columns for dim in alt))
    if not kept:
        raise ScopeCompileError(UNDECLARED)
    return kept


def compile_scope(
    query: str, columns: Mapping[str, str], scope: RowScope | None
) -> CompiledScope:
    """Replace every ``{{scope}}`` in ``query`` with the same bound predicate."""
    if uses_reserved_bind(query):
        raise ScopeCompileError(
            f"queries may not use the reserved {RESERVED_BIND_PREFIX}"
        )
    narrowed = narrow_scope(scope, columns)
    if narrowed is None:
        return CompiledScope(
            sql=query.replace(SCOPE_TOKEN, _UNRESTRICTED),
            params={},
            restricted=False,
            dimensions=(),
            alternatives=(),
        )
    if SCOPE_TOKEN not in query:
        raise ScopeCompileError("a row-scoped query must contain {{scope}}")

    params: dict[str, str] = {}
    clauses = [_alternative(i, alt, columns, params) for i, alt in enumerate(narrowed)]
    if len(params) > MAX_SCOPE_BINDS:
        raise ScopeCompileError(f"a row scope binds more than {MAX_SCOPE_BINDS} values")
    predicate = f"AND ({' OR '.join(clauses)})"
    dimensions = tuple(sorted({dim for alt in narrowed for dim in alt}))
    return CompiledScope(
        sql=query.replace(SCOPE_TOKEN, predicate),
        params=params,
        restricted=True,
        dimensions=dimensions,
        alternatives=narrowed,
    )


def _alternative(
    index: int,
    alternative: ScopeAlternative,
    columns: Mapping[str, str],
    params: dict[str, str],
) -> str:
    conditions: list[str] = []
    position = 0
    for dim in sorted(alternative):
        column = _safe_column(columns[dim])
        binds: list[str] = []
        for value in sorted(alternative[dim]):
            name = f"scope_{index}_{position}"
            position += 1
            params[name] = value
            binds.append(f":{name}")
        conditions.append(f"({column} IN ({', '.join(binds)}))")
    if len(conditions) == 1:
        return conditions[0]
    return f"({' AND '.join(conditions)})"


def _freeze(alternative: object) -> ScopeAlternative:
    """Validate one alternative and copy it into an immutable mapping.

    Typed as ``object``: scopes arrive from stored grants, so every shape is
    checked at runtime and any surprise fails closed as ``ScopeCompileError``.
    """
    if not isinstance(alternative, Mapping):
        raise ScopeCompileError("a row-scope alternative must be a mapping")
    items: Mapping[object, object] = alternative  # pyright: ignore[reportUnknownVariableType]
    if not items:
        raise ScopeCompileError("a row-scope alternative names no dimension")
    frozen: dict[str, frozenset[str]] = {}
    for dim, values in items.items():
        if not isinstance(dim, str):
            raise ScopeCompileError("row-scope dimensions must be strings")
        frozen[dim] = _freeze_values(values)
    return MappingProxyType(frozen)


def _freeze_values(values: object) -> frozenset[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Collection):
        raise ScopeCompileError("row-scope values must be a set of strings")
    members: Collection[object] = values  # pyright: ignore[reportUnknownVariableType]
    if not members:
        raise ScopeCompileError("a row-scope dimension lists no values")
    if len(members) > MAX_SCOPE_VALUES:
        raise ScopeCompileError(
            f"a row-scope dimension lists more than {MAX_SCOPE_VALUES} values"
        )
    strings = frozenset(v for v in members if isinstance(v, str))
    if len(strings) != len(members):
        raise ScopeCompileError("row-scope values must be a set of strings")
    return strings


def _safe_column(column: str) -> str:
    """Defense in depth: the registry lints columns; re-check before use."""
    if not COLUMN_PATTERN.fullmatch(column):
        raise ScopeCompileError("a scope dimension maps to an invalid column")
    return column
