"""Test doubles shared across test modules."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.access.patterns import matches
from app.atlas import AtlasCaller, AtlasRegistry, AtlasTools


@dataclass(frozen=True)
class StaticPolicy:
    """ResourcePolicy double: allows what any pattern matches, with the same
    matching as the production Policy (app.access.patterns.matches)."""

    allowed: Sequence[str] = ("*",)

    def allows(self, resource: str) -> bool:
        return any(matches(pattern, resource) for pattern in self.allowed)

    def deny_reason(self, resource: str) -> str:
        return "not in the test allowlist"


def make_tools(
    db: AsyncSession | None = None,
    registry: AtlasRegistry | None = None,
    *,
    allowed: Sequence[str] = ("*",),
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
    return AtlasTools(caller, StaticPolicy(allowed), db=db, registry=registry)
