"""Test doubles shared across test modules."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.patterns import matches
from app.atlas import AtlasCaller, AtlasRegistry, AtlasTools, RowScope

TEST_PSEUDONYM_KEY = "test-key"


@dataclass(frozen=True, slots=True)
class FakeMaskMode:
    """Satisfies atlas.MaskMode, like access.policy.LabelMode."""

    mode: str
    bucket_size: int = 5


def _no_modes() -> Mapping[str, tuple[str, int]]:
    return MappingProxyType({})


@dataclass(frozen=True)
class StaticPolicy:
    """ResourcePolicy double: allows what any pattern matches, with the same
    matching as the production Policy (app.access.patterns.matches).

    `row_scopes`: (pattern, scope) pairs; the first matching pattern wins and
    no match means all rows. `clearances=None` means cleared for everything, so
    breakdowns stay unmasked unless a test opts in. `modes`: label class ->
    (mode, bucket_size).
    """

    allowed: Sequence[str] = ("*",)
    row_scopes: Sequence[tuple[str, RowScope | None]] = ()
    clearances: frozenset[str] | None = None
    modes: Mapping[str, tuple[str, int]] = field(default_factory=_no_modes)

    def allows(self, resource: str) -> bool:
        return any(matches(pattern, resource) for pattern in self.allowed)

    def deny_reason(self, resource: str) -> str:
        return "not in the test allowlist"

    def row_scope(self, resource: str) -> RowScope | None:
        for pattern, scope in self.row_scopes:
            if matches(pattern, resource):
                return scope
        return None

    def has_clearance(self, clearance: str) -> bool:
        return self.clearances is None or clearance in self.clearances

    def mask_mode(self, label_class: str) -> FakeMaskMode | None:
        setting = self.modes.get(label_class)
        if setting is None:
            return None
        mode, bucket_size = setting
        return FakeMaskMode(mode, bucket_size)


def make_tools(
    db: AsyncSession | None = None,
    registry: AtlasRegistry | None = None,
    *,
    allowed: Sequence[str] = ("*",),
    row_scopes: Sequence[tuple[str, RowScope | None]] = (),
    clearances: frozenset[str] | None = None,
    modes: Mapping[str, tuple[str, int]] | None = None,
    pseudonym_key: str = TEST_PSEUDONYM_KEY,
    surface: str = "chat",
    user_id: UUID | None = None,
    session_id: UUID | None = None,
) -> AtlasTools:
    caller = AtlasCaller(
        user_id=user_id or uuid4(),
        auth_method="test",
        surface=surface,
        session_id=session_id,
    )
    policy = StaticPolicy(
        allowed,
        row_scopes=row_scopes,
        clearances=clearances,
        modes=MappingProxyType(dict(modes or {})),
    )
    return AtlasTools(
        caller, policy, db=db, registry=registry, pseudonym_key=pseudonym_key
    )
