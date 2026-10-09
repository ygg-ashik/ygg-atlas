"""All database access for users and their credentials. No business decisions here."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, cast
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    CursorResult,
    Delete,
    Result,
    Update,
    and_,
    delete,
    func,
    or_,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, col, select

from app.identity.api_tokens import CLIENT_IDLE_GC, REVOKED_ROTATED, TokenKind
from app.identity.models import (
    ApiToken,
    CredentialEvent,
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthCode,
    User,
)

# Garbage collection (D3): pending authorizations and codes live minutes, so a day
# is generous; dead OAuth token rows are kept a month for investigations.
PENDING_RETENTION: Final = timedelta(days=1)
OAUTH_TOKEN_RETENTION: Final = timedelta(days=30)
_OAUTH_KINDS: Final = (TokenKind.OAUTH_ACCESS, TokenKind.OAUTH_REFRESH)


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self, user_id: UUID) -> User | None:
        return await self._db.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._db.execute(
            select(User).where(col(User.email) == email.strip().lower())
        )
        return result.scalar_one_or_none()

    async def get_by_firebase_uid(self, firebase_uid: str) -> User | None:
        result = await self._db.execute(
            select(User).where(col(User.firebase_uid) == firebase_uid)
        )
        return result.scalar_one_or_none()

    async def save(self, user: User) -> User:
        user.email = user.email.strip().lower()
        self._db.add(user)
        await self._db.commit()
        await self._db.refresh(user)
        return user

    async def create_or_get(self, user: User) -> User:
        """Insert a new user; if a concurrent request inserted the same identity first,
        return that row instead (unique email / firebase_uid decide the winner).

        The insert runs in a SAVEPOINT, so a conflict never discards other pending
        work in the caller's session.
        """
        user.email = user.email.strip().lower()
        try:
            async with self._db.begin_nested():
                self._db.add(user)
        except IntegrityError:
            existing = None
            if user.firebase_uid:
                existing = await self.get_by_firebase_uid(user.firebase_uid)
            if existing is None:
                existing = await self.get_by_email(user.email)
            if existing is None:
                raise  # the conflict was on something other than identity
            # The winner's row is returned as-is; a differing firebase_uid is linked
            # by the caller's next sign-in (IdentityService._find_or_link).
            return existing
        await self._db.commit()
        await self._db.refresh(user)
        return user


@dataclass(frozen=True, slots=True)
class ConnectedAppRow:
    """One OAuth family with a live refresh token, joined to its client."""

    family_id: UUID
    client_id: str
    client_name: str | None
    redirect_uris: tuple[str, ...]
    created_at: datetime  # when the family began (its first token)
    last_used_at: datetime | None  # latest use of any token in the family
    expires_at: datetime  # the live refresh token's expiry


@dataclass(frozen=True, slots=True)
class GcCounts:
    codes: int
    requests: int
    tokens: int
    clients: int


def _rowcount(result: Result[Any]) -> int:
    # A DML statement always executes through a cursor, so this is a CursorResult
    # at runtime; AsyncSession.execute only types it as the base Result.
    return cast("CursorResult[Any]", result).rowcount


def _live_token(now: datetime) -> ColumnElement[bool]:
    return and_(col(ApiToken.revoked_at).is_(None), col(ApiToken.expires_at) > now)


class CredentialRepository:
    """Credential rows. Reads return rows; writes are staged and the calling service
    commits once, so a change and its credential_events row land together.

    Every "only once" write is one conditional UPDATE whose rowcount decides: on
    PostgreSQL READ COMMITTED the loser's UPDATE waits for the winner's row lock,
    re-checks its WHERE clause and matches 0 rows (D5, D6, D30).
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    def add(self, row: SQLModel) -> None:
        self._db.add(row)

    async def commit(self) -> None:
        await self._db.commit()

    async def rollback(self) -> None:
        await self._db.rollback()

    async def _update(self, statement: Update | Delete) -> int:
        """Run one UPDATE or DELETE and return the rows it matched. "fetch" keeps
        rows already loaded in this session in step with the database."""
        result = await self._db.execute(
            statement.execution_options(synchronize_session="fetch")
        )
        return _rowcount(result)

    # ---- tokens ----------------------------------------------------------

    async def token(self, token_id: UUID, *, fresh: bool = False) -> ApiToken | None:
        return await self._db.get(ApiToken, token_id, populate_existing=fresh)

    async def token_by_hash(self, token_hash: str) -> ApiToken | None:
        result = await self._db.execute(
            select(ApiToken).where(col(ApiToken.token_hash) == token_hash)
        )
        return result.scalar_one_or_none()

    async def list_tokens(
        self,
        *,
        tenant: str,
        kinds: Collection[str],
        user_id: UUID | None = None,
        include_revoked: bool = False,
        limit: int = 200,
    ) -> list[ApiToken]:
        statement = (
            select(ApiToken)
            .join(User, col(User.id) == col(ApiToken.user_id))
            .where(col(User.tenant) == tenant, col(ApiToken.kind).in_(list(kinds)))
        )
        if user_id is not None:
            statement = statement.where(col(ApiToken.user_id) == user_id)
        if not include_revoked:
            statement = statement.where(col(ApiToken.revoked_at).is_(None))
        statement = statement.order_by(col(ApiToken.created_at).desc()).limit(limit)
        return list((await self._db.execute(statement)).scalars().all())

    async def count_live(self, user_id: UUID, kind: str, now: datetime) -> int:
        result = await self._db.execute(
            select(func.count())
            .select_from(ApiToken)
            .where(
                col(ApiToken.user_id) == user_id,
                col(ApiToken.kind) == kind,
                _live_token(now),
            )
        )
        return result.scalar_one()

    async def revoke_token(self, token_id: UUID, reason: str, now: datetime) -> bool:
        return (
            await self._update(
                update(ApiToken)
                .where(col(ApiToken.id) == token_id, col(ApiToken.revoked_at).is_(None))
                .values(revoked_at=now, revoked_reason=reason)
            )
            == 1
        )

    async def mark_rotated(self, token_id: UUID, now: datetime) -> bool:
        """Exactly one concurrent refresh of a token sees True (D6)."""
        return await self.revoke_token(token_id, REVOKED_ROTATED, now)

    async def revoke_family(self, family_id: UUID, reason: str, now: datetime) -> int:
        """Revokes the family's live rows; never overwrites an earlier reason."""
        return await self._update(
            update(ApiToken)
            .where(
                col(ApiToken.family_id) == family_id, col(ApiToken.revoked_at).is_(None)
            )
            .values(revoked_at=now, revoked_reason=reason)
        )

    async def revoke_user_tokens(
        self, user_id: UUID, reason: str, now: datetime
    ) -> int:
        return await self._update(
            update(ApiToken)
            .where(col(ApiToken.user_id) == user_id, col(ApiToken.revoked_at).is_(None))
            .values(revoked_at=now, revoked_reason=reason)
        )

    async def revoke_client_tokens(
        self, client_id: str, reason: str, now: datetime
    ) -> int:
        return await self._update(
            update(ApiToken)
            .where(
                col(ApiToken.client_id) == client_id, col(ApiToken.revoked_at).is_(None)
            )
            .values(revoked_at=now, revoked_reason=reason)
        )

    async def family_has_live_token(self, family_id: UUID, now: datetime) -> bool:
        result = await self._db.execute(
            select(col(ApiToken.id))
            .where(col(ApiToken.family_id) == family_id, _live_token(now))
            .limit(1)
        )
        return result.first() is not None

    async def touch_token(self, token_id: UUID, now: datetime) -> None:
        await self._update(
            update(ApiToken)
            .where(col(ApiToken.id) == token_id)
            .values(last_used_at=now)
        )

    async def connected_apps(
        self, user_id: UUID, now: datetime
    ) -> list[ConnectedAppRow]:
        """One row per family that still has a live refresh token."""
        live = (
            await self._db.execute(
                select(ApiToken, OAuthClient)
                .join(
                    OAuthClient, col(OAuthClient.client_id) == col(ApiToken.client_id)
                )
                .where(
                    col(ApiToken.user_id) == user_id,
                    col(ApiToken.kind) == TokenKind.OAUTH_REFRESH,
                    col(ApiToken.family_id).is_not(None),
                    col(OAuthClient.revoked_at).is_(None),
                    _live_token(now),
                )
                .order_by(col(ApiToken.expires_at))
            )
        ).all()
        # A grace refresh (D6) may leave two live refresh tokens in one family
        # for a moment; the later expiry wins.
        latest: dict[UUID, tuple[ApiToken, OAuthClient]] = {}
        for token, client in live:
            if token.family_id is not None:
                latest[token.family_id] = (token, client)
        spans = await self._family_spans(list(latest))
        return [
            ConnectedAppRow(
                family_id=family_id,
                client_id=client.client_id,
                client_name=client.client_name,
                redirect_uris=tuple(client.redirect_uris),
                created_at=spans[family_id][0],
                last_used_at=spans[family_id][1],
                expires_at=token.expires_at,
            )
            for family_id, (token, client) in latest.items()
        ]

    async def _family_spans(
        self, family_ids: list[UUID]
    ) -> dict[UUID, tuple[datetime, datetime | None]]:
        if not family_ids:
            return {}
        rows = (
            await self._db.execute(
                select(
                    col(ApiToken.family_id),
                    func.min(col(ApiToken.created_at)),
                    func.max(col(ApiToken.last_used_at)),
                )
                .where(col(ApiToken.family_id).in_(family_ids))
                .group_by(col(ApiToken.family_id))
            )
        ).all()
        return {
            cast(UUID, family): (cast(datetime, first), cast("datetime | None", last))
            for family, first, last in rows
        }

    async def live_family_counts(self, now: datetime) -> dict[str, int]:
        """client_id -> number of families with a live refresh token."""
        rows = (
            await self._db.execute(
                select(
                    col(ApiToken.client_id),
                    func.count(func.distinct(col(ApiToken.family_id))),
                )
                .where(
                    col(ApiToken.kind) == TokenKind.OAUTH_REFRESH,
                    col(ApiToken.client_id).is_not(None),
                    _live_token(now),
                )
                .group_by(col(ApiToken.client_id))
            )
        ).all()
        return {cast(str, client): int(count) for client, count in rows}

    # ---- clients -----------------------------------------------------------

    async def client(self, client_id: str) -> OAuthClient | None:
        return await self._db.get(OAuthClient, client_id)

    async def list_clients(self, limit: int = 200) -> list[OAuthClient]:
        result = await self._db.execute(
            select(OAuthClient)
            .order_by(col(OAuthClient.registered_at).desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def revoke_client(self, client_id: str, now: datetime) -> bool:
        return (
            await self._update(
                update(OAuthClient)
                .where(
                    col(OAuthClient.client_id) == client_id,
                    col(OAuthClient.revoked_at).is_(None),
                )
                .values(revoked_at=now)
            )
            == 1
        )

    async def touch_client(self, client_id: str, now: datetime) -> None:
        await self._update(
            update(OAuthClient)
            .where(col(OAuthClient.client_id) == client_id)
            .values(last_used_at=now)
        )

    # ---- authorization requests and codes ------------------------------------

    async def pending_request(
        self, request_hash: str, now: datetime
    ) -> OAuthAuthorizationRequest | None:
        result = await self._db.execute(
            select(OAuthAuthorizationRequest).where(
                col(OAuthAuthorizationRequest.id) == request_hash,
                col(OAuthAuthorizationRequest.consumed_at).is_(None),
                col(OAuthAuthorizationRequest.expires_at) > now,
            )
        )
        return result.scalar_one_or_none()

    async def consume_request(
        self, request_hash: str, now: datetime
    ) -> OAuthAuthorizationRequest | None:
        """Single use (D36): exactly one concurrent consent sees the request."""
        consumed = await self._update(
            update(OAuthAuthorizationRequest)
            .where(
                col(OAuthAuthorizationRequest.id) == request_hash,
                col(OAuthAuthorizationRequest.consumed_at).is_(None),
                col(OAuthAuthorizationRequest.expires_at) > now,
            )
            .values(consumed_at=now)
        )
        if consumed != 1:
            return None
        return await self._db.get(
            OAuthAuthorizationRequest, request_hash, populate_existing=True
        )

    async def code_by_hash(self, code_hash: str) -> OAuthCode | None:
        result = await self._db.execute(
            select(OAuthCode).where(col(OAuthCode.code_hash) == code_hash)
        )
        return result.scalar_one_or_none()

    async def code(self, code_id: UUID, *, fresh: bool = False) -> OAuthCode | None:
        return await self._db.get(OAuthCode, code_id, populate_existing=fresh)

    async def mark_code_used(self, code_id: UUID, now: datetime) -> bool:
        """Single use (D5): exactly one caller ever sees True, on SQLite and on PG
        READ COMMITTED (the loser's UPDATE waits for the winner's row lock,
        re-checks used_at and matches 0 rows)."""
        return (
            await self._update(
                update(OAuthCode)
                .where(
                    col(OAuthCode.id) == code_id,
                    col(OAuthCode.used_at).is_(None),
                    col(OAuthCode.expires_at) > now,
                )
                .values(used_at=now)
            )
            == 1
        )

    # ---- events and garbage collection ---------------------------------------

    async def list_events(
        self, *, tenant: str, user_id: UUID | None = None, limit: int = 100
    ) -> list[CredentialEvent]:
        """Newest first. Events about no user (client registration, GC) belong to no
        tenant and are listed with every tenant's events unless a user is given."""
        statement = select(CredentialEvent).outerjoin(
            User, col(User.id) == col(CredentialEvent.user_id)
        )
        if user_id is not None:
            statement = statement.where(
                col(CredentialEvent.user_id) == user_id, col(User.tenant) == tenant
            )
        else:
            statement = statement.where(
                or_(col(User.tenant) == tenant, col(CredentialEvent.user_id).is_(None))
            )
        statement = statement.order_by(col(CredentialEvent.at).desc()).limit(limit)
        return list((await self._db.execute(statement)).scalars().all())

    async def delete_stale(self, now: datetime) -> GcCounts:
        """Codes and pending authorizations older than a day; OAuth token rows expired
        or revoked over 30 days ago; then clients revoked or idle for 90 days that
        no row references any more. PAT and service rows are never deleted."""
        pending_cutoff = now - PENDING_RETENTION
        codes = await self._update(
            delete(OAuthCode).where(col(OAuthCode.created_at) < pending_cutoff)
        )
        requests = await self._update(
            delete(OAuthAuthorizationRequest).where(
                col(OAuthAuthorizationRequest.created_at) < pending_cutoff
            )
        )
        token_cutoff = now - OAUTH_TOKEN_RETENTION
        tokens = await self._update(
            delete(ApiToken).where(
                col(ApiToken.kind).in_(_OAUTH_KINDS),
                or_(
                    col(ApiToken.expires_at) < token_cutoff,
                    col(ApiToken.revoked_at) < token_cutoff,
                ),
            )
        )
        clients = await self._delete_dead_clients(now - CLIENT_IDLE_GC)
        return GcCounts(codes=codes, requests=requests, tokens=tokens, clients=clients)

    async def _delete_dead_clients(self, idle_cutoff: datetime) -> int:
        client_id = col(OAuthClient.client_id)
        referenced = [
            select(col(ApiToken.id)).where(col(ApiToken.client_id) == client_id),
            select(col(OAuthCode.id)).where(col(OAuthCode.client_id) == client_id),
            select(col(OAuthAuthorizationRequest.id)).where(
                col(OAuthAuthorizationRequest.client_id) == client_id
            ),
        ]
        last_activity = func.coalesce(
            col(OAuthClient.last_used_at), col(OAuthClient.registered_at)
        )
        return await self._update(
            delete(OAuthClient).where(
                or_(
                    col(OAuthClient.revoked_at).is_not(None),
                    last_activity < idle_cutoff,
                ),
                *(~query.exists() for query in referenced),
            )
        )
