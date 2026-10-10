"""Administer access from a shell; there is no admin UI until phase 5 (decision D5).

    uv run python -m app.access.cli groups
    uv run python -m app.access.cli add-member ashik@yougotagift.com atlas-admins \
        --manager
    uv run python -m app.access.cli remove-member someone@yougotagift.com marketing
    uv run python -m app.access.cli grant group:atlas-admins allow '*' \
        --reason bootstrap
    uv run python -m app.access.cli grant user:dev@yougotagift.com allow '*' \
        --reason dev
    uv run python -m app.access.cli grant group:csm allow 'deepsales/*' \
        --scope 'csm=$self'
    uv run python -m app.access.cli grant group:b2c allow 'demo/order/*' \
        --scope 'channel=b2c'
    uv run python -m app.access.cli grant user:lead@yougotagift.com allow \
        fields:people_names --kind clearance
    uv run python -m app.access.cli revoke <grant-id>
    uv run python -m app.access.cli set-role someone@yougotagift.com analyst
    uv run python -m app.access.cli set-attr someone@yougotagift.com csm_name 'Sara K'
    uv run python -m app.access.cli unset-attr someone@yougotagift.com csm_name
    uv run python -m app.access.cli attrs someone@yougotagift.com
    uv run python -m app.access.cli label-classes
    uv run python -m app.access.cli label-class person_name bucket --bucket-size 3
    uv run python -m app.access.cli scope-dimensions
    uv run python -m app.access.cli access someone@yougotagift.com \
        --resource demo/order/revenue

Quote `'$self'` so the shell doesn't expand it. `--scope` repeats: values of one
dimension merge, different dimensions are ANDed.

On the server: `docker compose exec backend uv run --no-dev python -m app.access.cli
...`. Every change is recorded in rbac_changes with via="cli".

The CLI runs as a trusted operator with shell access to the box (D5): it skips
capability and D10 checks. Never construct Actor.cli() from request or agent code.

It operates on the default tenant only (single-tenant MVP); there is no --tenant flag.
"""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError

from app.access.admin import AccessAdmin, Actor
from app.access.cache import shared_cache
from app.access.errors import (
    AccessError,
    InvalidChangeError,
    NotFoundError,
    PolicyUnavailableError,
)
from app.access.facts import (
    DEFAULT_TENANT,
    KIND_CAPABILITY,
    KIND_CLEARANCE,
    KIND_RESOURCE,
    MASK_MODES,
    SUBJECT_GROUP,
    SUBJECT_USER,
)
from app.access.models import Group
from app.access.patterns import is_resource_path
from app.access.policy import Conjunction, RowScope
from app.access.repository import AccessRepository
from app.access.schemas import GrantCreate, UserUpdate
from app.access.service import AccessService
from app.database import get_engine, get_session_factory
from app.identity import User


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")


def _err(text: str) -> None:
    sys.stderr.write(text + "\n")


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if parsed.utcoffset() is None:
        msg = "--expires needs a UTC offset, e.g. 2027-01-01T00:00+04:00"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def _parse_scope(values: Sequence[str] | None) -> dict[str, list[str]] | None:
    """`['csm=$self', 'channel=b2c,b2b']` -> `{csm: [$self], channel: [b2c, b2b]}`.
    A dimension given twice merges its values; GrantCreate validates the rest."""
    if not values:
        return None
    scope: dict[str, list[str]] = {}
    for item in values:
        dimension, sep, raw = item.partition("=")
        parts = [v.strip() for v in raw.split(",") if v.strip()]
        if not sep or not dimension.strip() or not parts:
            msg = f"--scope '{item}' must look like dimension=value[,value...]"
            raise InvalidChangeError(msg)
        scope.setdefault(dimension.strip(), []).extend(parts)
    return scope


def _conjunction_text(conjunction: Conjunction) -> str:
    return " and ".join(
        f"{dimension} in ({', '.join(sorted(values))})"
        for dimension, values in conjunction
    )


def _rows_text(scope: RowScope | None) -> str:
    if scope is None:
        return "all"
    if not scope:
        return "none"
    return " OR ".join(_conjunction_text(tuple(sorted(alt.items()))) for alt in scope)


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
    subject_kind, _, name = str(args.subject).partition(":")
    label: str
    if subject_kind == SUBJECT_GROUP:
        group = await ctx.group(name)
        subject_id, label = group.id, group.name
    elif subject_kind == SUBJECT_USER:
        user = await ctx.user(name)
        subject_id, label = user.id, user.email
    else:
        msg = "The subject must be group:<name> or user:<email>."
        raise InvalidChangeError(msg)
    payload = GrantCreate.model_validate(
        {
            "subject_type": subject_kind,
            "subject_id": subject_id,
            "effect": args.effect,
            "target_kind": args.kind,
            "target": args.pattern,
            "reason": args.reason,
            "expires_at": args.expires,
            "row_scope": _parse_scope(args.scope),
        }
    )
    grant = await ctx.admin.create_grant(ctx.actor, payload)
    _out(f"granted {grant.id}: {grant.effect} {grant.target} to {label}")


async def _revoke(ctx: _Context, args: argparse.Namespace) -> None:
    await ctx.admin.revoke_grant(ctx.actor, UUID(args.grant_id))
    _out(f"revoked {args.grant_id}")


async def _set_role(ctx: _Context, args: argparse.Namespace) -> None:
    user = await ctx.user(args.email)
    await ctx.admin.update_user(ctx.actor, user.id, UserUpdate(role=args.role))
    _out(f"{user.email} is now {args.role}")


async def _access(ctx: _Context, args: argparse.Namespace) -> None:
    if args.resource is not None and not is_resource_path(args.resource):
        msg = f"'{args.resource}' is not a resource path like demo/order/revenue"
        raise InvalidChangeError(msg)
    user = await ctx.user(args.email)
    policy = await ctx.admin.effective_access(ctx.actor, user.id)
    state = "active" if policy.active else "disabled"
    _out(f"{user.email}: role {policy.role}, {state}")
    _out("capabilities: " + ", ".join(sorted(policy.capabilities)))
    _out("clearances: " + (", ".join(sorted(policy.clearances)) or "none"))
    for rule in policy.allow_rules:
        rows = "" if rule.scope is None else f"  rows: {_conjunction_text(rule.scope)}"
        _out(f"allow {rule.pattern}  ({rule.origin}, grant {rule.grant_id}){rows}")
    for rule in policy.deny_rules:
        _out(f"deny  {rule.pattern}  ({rule.origin}, grant {rule.grant_id})")
    for skipped in policy.skipped:
        _out(
            f"skipped {skipped.pattern}  ({skipped.origin}, grant {skipped.grant_id}): "
            f"{skipped.reason}"
        )
    if args.resource:
        _out(f"{args.resource}: {policy.decide(args.resource).reason}")
        # The policy view; the atlas also drops dimensions the entity lacks (D3.7).
        _out(f"rows: {_rows_text(policy.row_scope(args.resource))}")


async def _set_attr(ctx: _Context, args: argparse.Namespace) -> None:
    user = await ctx.user(args.email)
    await ctx.admin.set_attribute(ctx.actor, user.id, args.key, args.value)
    _out(f"{user.email}: attribute {args.key} set")


async def _unset_attr(ctx: _Context, args: argparse.Namespace) -> None:
    user = await ctx.user(args.email)
    await ctx.admin.delete_attribute(ctx.actor, user.id, args.key)
    _out(f"{user.email}: attribute {args.key} removed")


async def _attrs(ctx: _Context, args: argparse.Namespace) -> None:
    user = await ctx.user(args.email)
    rows = await ctx.admin.list_attributes(ctx.actor, user.id)
    if not rows:
        _out(f"{user.email} has no attributes")
    for row in rows:
        _out(f"{row.key} = {row.value}")


async def _label_classes(ctx: _Context, _args: argparse.Namespace) -> None:
    for row in await ctx.admin.list_label_classes(ctx.actor):
        _out(f"{row.label_class}: {row.mode} (bucket size {row.bucket_size})")


async def _label_class(ctx: _Context, args: argparse.Namespace) -> None:
    row = await ctx.admin.set_label_class(
        ctx.actor, args.label_class, args.mode, args.bucket_size
    )
    _out(f"{row.label_class}: {row.mode} (bucket size {row.bucket_size})")


async def _scope_dimensions(ctx: _Context, _args: argparse.Namespace) -> None:
    rows = await ctx.admin.list_scope_dimensions(ctx.actor)
    if not rows:
        _out("no scope dimensions (no enabled plugin declares any)")
    for row in rows:
        own = f"  ($self -> {row.self_attribute})" if row.self_attribute else ""
        note = f"  {row.description}" if row.description else ""
        _out(f"{row.source}/{row.entity}  {row.dimension}{own}{note}")


_COMMANDS: dict[str, _Command] = {
    "groups": _groups,
    "add-member": _add_member,
    "remove-member": _remove_member,
    "grant": _grant,
    "revoke": _revoke,
    "set-role": _set_role,
    "access": _access,
    "set-attr": _set_attr,
    "unset-attr": _unset_attr,
    "attrs": _attrs,
    "label-classes": _label_classes,
    "label-class": _label_class,
    "scope-dimensions": _scope_dimensions,
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
    grant.add_argument(
        "--kind",
        choices=[KIND_RESOURCE, KIND_CAPABILITY, KIND_CLEARANCE],
        default=KIND_RESOURCE,
        help="what 'pattern' names (default: resource)",
    )
    grant.add_argument(
        "--scope",
        action="append",
        default=None,
        metavar="DIM=V1[,V2]",
        help="limit rows, e.g. 'csm=$self' or 'channel=b2c,b2b' (repeatable)",
    )
    grant.add_argument("--reason", default="")
    grant.add_argument(
        "--expires",
        default=None,
        type=_aware_datetime,
        help="ISO time with a UTC offset, e.g. 2027-01-01T00:00+04:00",
    )
    revoke = sub.add_parser("revoke", help="delete a grant")
    revoke.add_argument("grant_id")
    role = sub.add_parser("set-role", help="change a user's role")
    role.add_argument("email")
    role.add_argument("role")
    show = sub.add_parser("access", help="explain a user's effective access")
    show.add_argument("email")
    show.add_argument("--resource", default=None)
    set_attr = sub.add_parser("set-attr", help="set a user attribute ($self uses it)")
    set_attr.add_argument("email")
    set_attr.add_argument("key")
    set_attr.add_argument("value")
    unset_attr = sub.add_parser("unset-attr", help="remove a user attribute")
    unset_attr.add_argument("email")
    unset_attr.add_argument("key")
    attrs = sub.add_parser("attrs", help="list a user's attributes")
    attrs.add_argument("email")
    sub.add_parser("label-classes", help="how masked label classes are shown")
    label = sub.add_parser("label-class", help="set how a label class is masked")
    label.add_argument("label_class", help="business_name or person_name")
    label.add_argument("mode", choices=list(MASK_MODES))
    label.add_argument("--bucket-size", type=int, default=None)
    sub.add_parser("scope-dimensions", help="dimensions a row scope may name")
    return parser


async def run(argv: Sequence[str]) -> int:
    args = _parser().parse_args(argv)
    async with get_session_factory()() as db:
        repo = AccessRepository(db)
        admin = AccessAdmin(repo, AccessService(repo, shared_cache()))
        try:
            await _COMMANDS[args.command](_Context(admin, repo, Actor.cli()), args)
        except PolicyUnavailableError:
            _err(
                "error: atlas access isn't initialised yet. "
                "Start the backend once, then retry."
            )
            return 1
        except ValidationError as exc:
            _err("error: " + "; ".join(e["msg"] for e in exc.errors()))
            return 1
        except (AccessError, ValueError) as exc:  # ValueError covers bad UUIDs/input
            _err(f"error: {exc}")
            return 1
    return 0


def main() -> None:
    async def _main(argv: Sequence[str]) -> int:
        try:
            return await run(argv)
        finally:
            # Tests share the process-wide engine; only the real CLI process
            # disposes it, and only once it actually exists (argparse errors
            # and --help exit before `run` ever opens a session, so building
            # an engine just to dispose it would needlessly require settings).
            if get_engine.cache_info().currsize:
                await get_engine().dispose()

    raise SystemExit(asyncio.run(_main(sys.argv[1:])))


if __name__ == "__main__":
    main()
