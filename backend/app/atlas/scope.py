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
from collections.abc import Collection, Mapping
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
_BIND_PREFIX: Final = ":scope_"  # reserved for generated bind names
_COLUMN: Final = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)?")


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
    if _BIND_PREFIX in query:
        raise ScopeCompileError(f"queries may not use the reserved {_BIND_PREFIX}")
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
    if not _COLUMN.fullmatch(column):
        raise ScopeCompileError("a scope dimension maps to an invalid column")
    return column
