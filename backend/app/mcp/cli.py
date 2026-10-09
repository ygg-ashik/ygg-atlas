"""Administer MCP credentials from a shell until phase 5 ships the admin UI (D23).

    uv run python -m app.mcp.cli create-pat someone@yougotagift.com --name laptop
    uv run python -m app.mcp.cli create-service-account "Nightly ETL" --role analyst
    uv run python -m app.mcp.cli create-service-token svc-nightly-etl@atlas.internal
    uv run python -m app.mcp.cli list-tokens [--email E] [--kind pat|service|oauth]
    uv run python -m app.mcp.cli revoke-token <token-id> [--reason R]
    uv run python -m app.mcp.cli revoke-all someone@yougotagift.com
    uv run python -m app.mcp.cli list-clients
    uv run python -m app.mcp.cli revoke-client <client-id>
    uv run python -m app.mcp.cli gc

On the server: `docker compose exec backend uv run --no-dev python -m app.mcp.cli ...`.

Like `app.access.cli`, this runs as the trusted operator with shell access to the box
(D5): `Actor.cli()` for access writes and `CredentialActor(None, "cli")` for
credential writes, so every change is recorded with via="cli". A minted token is
written to stdout exactly once, on its own line; it never reaches a log, an event or
stderr. Exit codes: 0 ok, 1 domain error (message on stderr), 2 usage.

It operates on the default tenant only (single-tenant MVP); there is no --tenant flag.
"""

import argparse
import asyncio
import re
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from app.access import (
    AccessAdmin,
    AccessError,
    Actor,
    PolicyUnavailableError,
    get_access_admin,
)
from app.config import Settings, get_settings
from app.database import get_engine, get_session_factory
from app.identity import (
    REVOKED_BY_ADMIN,
    ApiToken,
    CredentialActor,
    CredentialLimitError,
    CredentialNotFoundError,
    CredentialRuleError,
    IssuedToken,
    OAuthConfig,
    OAuthService,
    TokenKind,
    TokenService,
    User,
    get_token_verifier,
)

STORE_NOTICE: Final = "Store this token now: it won't be shown again."
_CLI_ACTOR: Final = CredentialActor(None, "cli")
_KINDS: Final[Mapping[str, tuple[TokenKind, ...]]] = {
    "pat": (TokenKind.PAT,),
    "service": (TokenKind.SERVICE,),
    "oauth": (TokenKind.OAUTH_ACCESS, TokenKind.OAUTH_REFRESH),
}
_DEFAULT_KINDS: Final = (TokenKind.PAT, TokenKind.SERVICE)
# api_tokens.revoked_reason is varchar(32); reasons are machine-readable words.
_REASON: Final = re.compile(r"[a-z][a-z0-9_]{0,31}")
# list_users matches by substring; an exact email has few supersets.
_EMAIL_MATCHES: Final = 50
# Owner emails for list-tokens: the single-tenant MVP has far fewer users.
_OWNER_LOOKUP: Final = 10_000


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")


def _err(text: str) -> None:
    sys.stderr.write(text + "\n")


def _printable(text: str) -> str:
    """Names come from users and DCR clients: keep terminal control codes out."""
    return "".join(char if char.isprintable() else "?" for char in text)


def _when(moment: datetime | None) -> str:
    if moment is None:
        return "-"
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat(timespec="seconds")


def _reason(value: str) -> str:
    if not _REASON.fullmatch(value):
        msg = "use 1-32 lowercase letters, digits or underscores, e.g. leaked"
        raise argparse.ArgumentTypeError(msg)
    return value


@dataclass(frozen=True, slots=True)
class _Context:
    admin: AccessAdmin
    tokens: TokenService
    oauth: OAuthService
    settings: Settings
    actor: Actor

    async def user(self, email: str) -> User:
        wanted = email.strip().casefold()
        for user in await self.admin.list_users(self.actor, wanted, _EMAIL_MATCHES):
            if user.email.casefold() == wanted:
                return user
        msg = f"No user {_printable(email)}. They must sign in to atlas once first."
        raise CredentialNotFoundError(msg)


type _Command = Callable[[_Context, argparse.Namespace], Awaitable[None]]


def _show_issued(issued: IssuedToken) -> None:
    """The one place a raw token is written: stdout, once, last, on its own line."""
    token = issued.token
    _out(f"id: {token.id}")
    _out(f"prefix: {token.prefix}")
    _out(f"expires_at: {_when(token.expires_at)}")
    _err(STORE_NOTICE)
    _out(issued.raw)


async def _create_pat(ctx: _Context, args: argparse.Namespace) -> None:
    user = await ctx.user(args.email)
    issued = await ctx.tokens.create_pat(
        user.id,
        name=args.name,
        expires_in_days=args.days,
        actor=_CLI_ACTOR,
        default_days=ctx.settings.pat_default_days,
        max_days=ctx.settings.pat_max_days,
    )
    _show_issued(issued)


async def _create_service_account(ctx: _Context, args: argparse.Namespace) -> None:
    account = await ctx.admin.create_service_account(ctx.actor, args.name, args.role)
    _out(f"created {account.email} ({account.role})")


async def _create_service_token(ctx: _Context, args: argparse.Namespace) -> None:
    account = await ctx.user(args.email)
    issued = await ctx.tokens.create_service_token(
        account.id,
        name=args.name,
        expires_in_days=args.days,
        actor=_CLI_ACTOR,
        default_days=ctx.settings.pat_default_days,
        max_days=ctx.settings.pat_max_days,
    )
    _show_issued(issued)


def _token_line(token: ApiToken, owner: str) -> str:
    revoked = (
        f"revoked {_when(token.revoked_at)} ({token.revoked_reason})"
        if token.revoked_at is not None
        else "live"
    )
    return (
        f"{token.id}  {token.kind}  {token.prefix}  {owner}  "
        f"expires {_when(token.expires_at)}  last used {_when(token.last_used_at)}  "
        f"{revoked}  {_printable(token.name)}"
    )


async def _list_tokens(ctx: _Context, args: argparse.Namespace) -> None:
    user = None if args.email is None else await ctx.user(args.email)
    tokens = await ctx.tokens.list_tokens(
        tenant=ctx.actor.tenant,
        user_id=None if user is None else user.id,
        kinds=_DEFAULT_KINDS if args.kind is None else _KINDS[args.kind],
        include_revoked=args.include_revoked,
    )
    if not tokens:
        _out("no tokens")
        return
    owners = (
        {user.id: user.email}
        if user is not None
        else {
            u.id: u.email
            for u in await ctx.admin.list_users(ctx.actor, "", _OWNER_LOOKUP)
        }
    )
    for token in tokens:
        _out(_token_line(token, owners.get(token.user_id, str(token.user_id))))


async def _revoke_token(ctx: _Context, args: argparse.Namespace) -> None:
    token_id = UUID(args.token_id)
    await ctx.tokens.revoke_token(
        token_id, reason=args.reason, actor=_CLI_ACTOR, tenant=ctx.actor.tenant
    )
    _out(f"revoked {token_id}")


async def _revoke_all(ctx: _Context, args: argparse.Namespace) -> None:
    user = await ctx.user(args.email)
    count = await ctx.tokens.revoke_all_tokens(
        user.id, reason=REVOKED_BY_ADMIN, actor=_CLI_ACTOR
    )
    _out(f"revoked {count} tokens of {user.email}")


async def _list_clients(ctx: _Context, _args: argparse.Namespace) -> None:
    clients = await ctx.oauth.list_clients()
    if not clients:
        _out("no clients")
        return
    for client in clients:
        state = (
            "live"
            if client.revoked_at is None
            else f"revoked {_when(client.revoked_at)}"
        )
        redirects = ", ".join(_printable(uri) for uri in client.redirect_uris)
        _out(
            f"{_printable(client.client_id)}  {_printable(client.client_name)}  "
            f"{client.token_endpoint_auth_method}  "
            f"registered {_when(client.registered_at)}  "
            f"connected {client.active_families}  {state}  {redirects}"
        )


async def _revoke_client(ctx: _Context, args: argparse.Namespace) -> None:
    if not await ctx.oauth.revoke_client(args.client_id, actor=_CLI_ACTOR):
        msg = f"No active client {_printable(args.client_id)}."
        raise CredentialNotFoundError(msg)
    _out(f"revoked client {_printable(args.client_id)} and its tokens")


async def _gc(ctx: _Context, _args: argparse.Namespace) -> None:
    report = await ctx.oauth.gc()
    _out(f"codes: {report.codes}")
    _out(f"requests: {report.requests}")
    _out(f"tokens: {report.tokens}")
    _out(f"clients: {report.clients}")


_COMMANDS: dict[str, _Command] = {
    "create-pat": _create_pat,
    "create-service-account": _create_service_account,
    "create-service-token": _create_service_token,
    "list-tokens": _list_tokens,
    "revoke-token": _revoke_token,
    "revoke-all": _revoke_all,
    "list-clients": _list_clients,
    "revoke-client": _revoke_client,
    "gc": _gc,
}


def _add_mint_options(parser: argparse.ArgumentParser, default_name: str) -> None:
    parser.add_argument("--name", default=default_name, help="a label, 1-100 chars")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="lifetime in days (default PAT_DEFAULT_DAYS)",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.mcp.cli", description="Administer MCP credentials."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    pat = sub.add_parser("create-pat", help="mint a personal token (shown once)")
    pat.add_argument("email")
    _add_mint_options(pat, "cli")
    account = sub.add_parser("create-service-account", help="create a service account")
    account.add_argument("name")
    account.add_argument("--role", required=True)
    service = sub.add_parser(
        "create-service-token", help="mint a service token (shown once)"
    )
    service.add_argument("email", help="the svc-…@atlas.internal email")
    _add_mint_options(service, "cli")
    listing = sub.add_parser("list-tokens", help="list tokens (never their secrets)")
    listing.add_argument("--email", default=None)
    listing.add_argument("--kind", choices=sorted(_KINDS), default=None)
    listing.add_argument("--include-revoked", action="store_true")
    revoke = sub.add_parser("revoke-token", help="revoke one token")
    revoke.add_argument("token_id")
    revoke.add_argument("--reason", type=_reason, default=REVOKED_BY_ADMIN)
    revoke_all = sub.add_parser("revoke-all", help="revoke every token of a user")
    revoke_all.add_argument("email")
    sub.add_parser("list-clients", help="list registered OAuth clients")
    client = sub.add_parser("revoke-client", help="revoke a client and its tokens")
    client.add_argument("client_id")
    sub.add_parser("gc", help="delete stale codes, requests, tokens and clients")
    return parser


async def run(argv: Sequence[str]) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    async with get_session_factory()() as db:
        ctx = _Context(
            admin=get_access_admin(db, get_token_verifier(settings)),
            tokens=TokenService(db),
            oauth=OAuthService(db, OAuthConfig.from_settings(settings)),
            settings=settings,
            actor=Actor.cli(),
        )
        try:
            await _COMMANDS[args.command](ctx, args)
        except PolicyUnavailableError:
            _err(
                "error: atlas access isn't initialised yet. "
                "Start the backend once, then retry."
            )
            return 1
        except (
            AccessError,
            CredentialRuleError,
            CredentialLimitError,
            CredentialNotFoundError,
            ValueError,  # malformed UUIDs
        ) as exc:
            _err(f"error: {exc}")
            return 1
    return 0


def main() -> None:
    async def _main(argv: Sequence[str]) -> int:
        try:
            return await run(argv)
        finally:
            # As in app.access.cli: tests share the engine; only a real CLI process
            # disposes it, and only once it exists.
            if get_engine.cache_info().currsize:
                await get_engine().dispose()

    raise SystemExit(asyncio.run(_main(sys.argv[1:])))


if __name__ == "__main__":
    main()
