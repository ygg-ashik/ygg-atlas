"""Test doubles shared across test modules."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.atlas import AtlasCaller, AtlasRegistry, AtlasTools


@dataclass(frozen=True)
class StaticPolicy:
    """ResourcePolicy double: '*', exact paths and 'prefix/*' patterns."""

    allowed: Sequence[str] = ("*",)

    def allows(self, resource: str) -> bool:
        return any(
            pattern in ("*", resource)
            or (pattern.endswith("/*") and resource.startswith(pattern[:-1]))
            for pattern in self.allowed
        )

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
