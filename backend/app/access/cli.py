"""Administer access from a shell; there is no admin UI until phase 5 (decision D5).

    uv run python -m app.access.cli groups
    uv run python -m app.access.cli add-member ashik@yougotagift.com atlas-admins \
        --manager
    uv run python -m app.access.cli remove-member someone@yougotagift.com marketing
    uv run python -m app.access.cli grant group:atlas-admins allow '*' \
        --reason bootstrap
    uv run python -m app.access.cli grant user:dev@yougotagift.com allow '*' \
        --reason dev
    uv run python -m app.access.cli revoke <grant-id>
    uv run python -m app.access.cli set-role someone@yougotagift.com analyst
    uv run python -m app.access.cli access someone@yougotagift.com \
        --resource demo/order/revenue

On the server: `docker compose exec backend uv run --no-dev python -m app.access.cli
...`. Every change is recorded in rbac_changes with via="cli".
"""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.access.admin import AccessAdmin, Actor
from app.access.cache import shared_cache
from app.access.errors import AccessError, InvalidChangeError, NotFoundError
from app.access.facts import DEFAULT_TENANT, SUBJECT_GROUP, SUBJECT_USER
from app.access.models import Group
from app.access.repository import AccessRepository
from app.access.schemas import GrantCreate, UserUpdate
from app.access.service import AccessService
from app.database import get_session_factory
from app.identity import User


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")


@dataclass(frozen=True, slots=True)
class _Context:
    admin: AccessAdmin
    repo: AccessRepository
    actor: Actor

    async def group(self, name: str) -> Group:
        group = await self.repo.group_by_name(DEFAULT_TENANT, name)
        if group is None:
            msg = f"No group named '{name}'. Run `groups` to list them."
            raise NotFoundError(msg)
        return group

    async def user(self, email: str) -> User:
        user = await self.repo.user_by_email(email)
        if user is None:
            msg = f"No user {email}. They must sign in to atlas once first."
            raise NotFoundError(msg)
        return user


type _Command = Callable[[_Context, argparse.Namespace], Awaitable[None]]


async def _groups(ctx: _Context, _args: argparse.Namespace) -> None:
    by_parent: dict[UUID | None, list[Group]] = {}
    for group in await ctx.admin.list_groups(ctx.actor):
        by_parent.setdefault(group.parent_id, []).append(group)

    def show(parent: UUID | None, depth: int) -> None:
        for group in by_parent.get(parent, []):
            _out(f"{'  ' * depth}{group.name}  ({group.id})")
            show(group.id, depth + 1)

    show(None, 0)


async def _add_member(ctx: _Context, args: argparse.Namespace) -> None:
    group = await ctx.group(args.group)
    user = await ctx.user(args.email)
    standing = "manager" if args.manager else "member"
    await ctx.admin.put_member(ctx.actor, group.id, user.id, standing)
    _out(f"{user.email} is now a {standing} of {group.name}")


async def _remove_member(ctx: _Context, args: argparse.Namespace) -> None:
    group = await ctx.group(args.group)
    user = await ctx.user(args.email)
    await ctx.admin.remove_member(ctx.actor, group.id, user.id)
    _out(f"{user.email} removed from {group.name}")


async def _grant(ctx: _Context, args: argparse.Namespace) -> None:
    kind, _, name = str(args.subject).partition(":")
    if kind == SUBJECT_GROUP:
        subject_id = (await ctx.group(name)).id
    elif kind == SUBJECT_USER:
        subject_id = (await ctx.user(name)).id
    else:
        msg = "The subject must be group:<name> or user:<email>."
        raise InvalidChangeError(msg)
    payload = GrantCreate.model_validate(
        {
            "subject_type": kind,
            "subject_id": subject_id,
            "effect": args.effect,
            "target": args.pattern,
            "reason": args.reason,
            "expires_at": args.expires,
        }
    )
    grant = await ctx.admin.create_grant(ctx.actor, payload)
    _out(f"granted {grant.id}: {grant.effect} {grant.target} to {args.subject}")


async def _revoke(ctx: _Context, args: argparse.Namespace) -> None:
    await ctx.admin.revoke_grant(ctx.actor, UUID(args.grant_id))
    _out(f"revoked {args.grant_id}")


async def _set_role(ctx: _Context, args: argparse.Namespace) -> None:
    user = await ctx.user(args.email)
    await ctx.admin.update_user(ctx.actor, user.id, UserUpdate(role=args.role))
    _out(f"{user.email} is now {args.role}")


async def _access(ctx: _Context, args: argparse.Namespace) -> None:
    user = await ctx.user(args.email)
    policy = await ctx.admin.effective_access(ctx.actor, user.id)
    state = "active" if policy.active else "disabled"
    _out(f"{user.email}: role {policy.role}, {state}")
    _out("capabilities: " + ", ".join(sorted(policy.capabilities)))
    for rule in policy.allow_rules:
        _out(f"allow {rule.pattern}  ({rule.origin}, grant {rule.grant_id})")
    for rule in policy.deny_rules:
        _out(f"deny  {rule.pattern}  ({rule.origin}, grant {rule.grant_id})")
    if args.resource:
        _out(f"{args.resource}: {policy.decide(args.resource).reason}")


_COMMANDS: dict[str, _Command] = {
    "groups": _groups,
    "add-member": _add_member,
    "remove-member": _remove_member,
    "grant": _grant,
    "revoke": _revoke,
    "set-role": _set_role,
    "access": _access,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.access.cli", description="Administer atlas access."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("groups", help="list groups as a tree")
    add = sub.add_parser("add-member", help="add a user to a group")
    add.add_argument("email")
    add.add_argument("group")
    add.add_argument("--manager", action="store_true")
    remove = sub.add_parser("remove-member", help="remove a user from a group")
    remove.add_argument("email")
    remove.add_argument("group")
    grant = sub.add_parser("grant", help="allow or deny a resource pattern")
    grant.add_argument("subject", help="group:<name> or user:<email>")
    grant.add_argument("effect", choices=["allow", "deny"])
    grant.add_argument("pattern", help="e.g. '*', 'deepsales/*', 'demo/order/revenue'")
    grant.add_argument("--reason", default="")
    grant.add_argument("--expires", default=None, help="ISO time with offset")
    revoke = sub.add_parser("revoke", help="delete a grant")
    revoke.add_argument("grant_id")
    role = sub.add_parser("set-role", help="change a user's role")
    role.add_argument("email")
    role.add_argument("role")
    show = sub.add_parser("access", help="explain a user's effective access")
    show.add_argument("email")
    show.add_argument("--resource", default=None)
    return parser


async def run(argv: Sequence[str]) -> int:
    args = _parser().parse_args(argv)
    async with get_session_factory()() as db:
        repo = AccessRepository(db)
        admin = AccessAdmin(repo, AccessService(repo, shared_cache()))
        try:
            await _COMMANDS[args.command](_Context(admin, repo, Actor.cli()), args)
        except (AccessError, ValueError) as exc:  # ValueError covers bad UUIDs/input
            _out(f"error: {exc}")
            return 1
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run(sys.argv[1:])))


if __name__ == "__main__":
    main()
