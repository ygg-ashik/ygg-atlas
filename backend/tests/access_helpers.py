"""Direct-to-database helpers for tests. They skip AccessAdmin on purpose."""

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.access.models import Grant, Group, GroupMember, PolicyState
from app.identity.models import User


async def make_user(
    db: AsyncSession,
    email: str,
    *,
    role: str = "viewer",
    status: str = "active",
    kind: str = "human",
) -> User:
    """Get or create. AUTH_DISABLED may already have created this email
    (the dev user) before a test gets a chance to, so this upserts rather
    than insert, which would otherwise hit the email unique constraint."""
    user = (
        await db.execute(select(User).where(col(User.email) == email))
    ).scalar_one_or_none()
    existed = user is not None
    if user is None:
        user = User(email=email, role=role, status=status, kind=kind)
    else:
        user.role = role
        user.status = status
        user.kind = kind
    db.add(user)
    await db.commit()
    if existed:
        # A role/status change on an already-cached policy needs a version
        # bump too, same as a grant or membership change.
        await bump(db)
    return user


async def make_group(
    db: AsyncSession, name: str, *, parent: Group | None = None
) -> Group:
    group = Group(name=name, parent_id=parent.id if parent else None)
    db.add(group)
    await db.commit()
    return group


async def add_member(
    db: AsyncSession, group: Group, user: User, standing: str = "member"
) -> GroupMember:
    member = GroupMember(group_id=group.id, user_id=user.id, standing=standing)
    db.add(member)
    await db.commit()
    await bump(db)
    return member


async def add_grant(
    db: AsyncSession,
    subject: Group | User,
    target: str = "*",
    *,
    effect: str = "allow",
    kind: str = "resource",
    expires_at: datetime | None = None,
    bump_version: bool = True,
) -> Grant:
    grant = Grant(
        subject_type="group" if isinstance(subject, Group) else "user",
        subject_id=subject.id,
        effect=effect,
        target_kind=kind,
        target=target,
        reason="test",
        expires_at=expires_at,
    )
    db.add(grant)
    await db.commit()
    if bump_version:
        await bump(db)
    return grant


async def bump(db: AsyncSession) -> None:
    await db.execute(
        update(PolicyState)
        .where(col(PolicyState.id) == 1)
        .values(policy_version=col(PolicyState.policy_version) + 1)
    )
    await db.commit()


async def grant_all(
    db: AsyncSession, email: str = "dev@yougotagift.com", *, role: str = "viewer"
) -> User:
    """What `make dev-access` does locally: give one user every resource."""
    user = (
        await db.execute(select(User).where(col(User.email) == email))
    ).scalar_one_or_none()
    if user is None:
        user = await make_user(db, email, role=role)
    else:
        user.role = role
        db.add(user)
        await db.commit()
    await add_grant(db, user, "*")
    return user
