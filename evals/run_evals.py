"""Golden-suite replay harness for the ygg-atlas agent.

Runs each golden question through the real agent loop (the configured LLM provider
and the seeded demo data) and checks tool usage, provenance, answer blocks and
answer content (`expect_*` fields; see goldens/core_metrics.yaml, plus
`expect_none`: substrings that must NOT appear anywhere the user sees: the answer,
its blocks and its provenance, case-insensitive).

Usage (from backend/, so the installed `app` package and its venv are used):
    uv run python ../evals/run_evals.py [--filter SUBSTRING]

Requires: an LLM key (OPENAI_API_KEY or ANTHROPIC_API_KEY), seeded demo data
(uv run python scripts/seed_demo.py), and the ygg-atlas database per backend/.env.

Access: each golden runs under a synthetic, in-memory policy built from the golden,
never from the grants in the database. This is an operator-only tool, run on a
trusted box; it is not an access path for users. Golden access fields (all optional):
    allow:        resource patterns (default ["*"], everything); an entry is a plain
                  pattern string or `{pattern, row_scope: {dimension: [values]}}`
                  (values may hold "$self")
    attributes:   `{key: value}` user attributes that `$self` resolves against;
                  the built-ins `email` and `user_id` always come from the eval user
    clearances:   field-clearance codes granted (e.g. fields:people_names)
    label_modes:  `{label_class: {mode, bucket_size}}` overriding the defaults
                  (person_name suppress, business_name pseudonymise; bucket 5),
                  which mirror the settings migration 0004 seeds
"""

import argparse
import asyncio
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import yaml

from app.access import GrantFacts, Policy, PolicyInputs, UserFacts, evaluate
from app.agent import run_chat_turn
from app.atlas import AtlasCaller, AtlasTools, get_registry
from app.config import get_settings
from app.database import get_session_factory
from app.identity import User, UserKind, UserStatus, ensure_service_user
from app.models import ChatSession

GOLDENS_DIR = Path(__file__).parent / "goldens"

# Numbers that may legitimately appear in prose without being data claims.
_INNOCENT_NUMBERS = {"1", "2", "3", "7", "24", "30", "90", "100", "2025", "2026"}

Golden = dict[str, Any]
Provenance = list[dict[str, Any]]


def _load_goldens(filter_substr: str | None) -> list[Golden]:
    goldens: list[Golden] = []
    for path in sorted(GOLDENS_DIR.glob("*.yaml")):
        goldens.extend(yaml.safe_load(path.read_text()) or [])
    if filter_substr:
        goldens = [g for g in goldens if filter_substr in g["id"]]
    return goldens


def _fmt_variants(value: float) -> list[str]:
    """Accept 10500, 10,500, 10500.0, 10,500.00 style renderings."""
    n = float(value)
    variants = [f"{n:g}", f"{n:,.0f}", f"{n:.0f}", f"{n:,.2f}", f"{n:.2f}", f"{n:,.1f}"]
    return list(dict.fromkeys(variants))


@dataclass
class Turn:
    """What one agent turn produced, as the checks see it."""

    answer: str = ""
    tools_used: list[str] = field(default_factory=list[str])
    provenance: Provenance = field(default_factory=list[dict[str, Any]])
    blocks: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])


def _check_tool(golden: Golden, turn: Turn) -> str:
    tool = golden.get("expect_tool")
    if tool and tool not in turn.tools_used:
        return f"expected tool '{tool}' to run; used {turn.tools_used}"
    return ""


def _check_metric(golden: Golden, turn: Turn) -> str:
    metric = golden.get("expect_metric")
    metric_ids = {p.get("metric_id") for p in turn.provenance}
    if metric and metric not in metric_ids:
        return f"expected metric '{metric}' in provenance; got {metric_ids}"
    return ""


def _check_value(golden: Golden, turn: Turn) -> str:
    value = golden.get("expect_value")
    if value is not None and not any(v in turn.answer for v in _fmt_variants(value)):
        return f"expected value {value} in answer"
    return ""


def _check_any(golden: Golden, turn: Turn) -> str:
    any_of = golden.get("expect_any")
    if any_of and not any(s.lower() in turn.answer.lower() for s in any_of):
        return f"expected one of {any_of} in answer"
    return ""


def _check_no_numbers(golden: Golden, turn: Turn) -> str:
    if not golden.get("expect_no_numbers"):
        return ""
    numbers = set(re.findall(r"\d[\d,\.]*", turn.answer)) - _INNOCENT_NUMBERS
    if numbers:
        return f"expected no data numbers, found {sorted(numbers)[:5]}"
    return ""


def _check_clarify(golden: Golden, turn: Turn) -> str:
    if golden.get("expect_clarify") and not any(
        b.get("kind") == "clarify" for b in turn.blocks
    ):
        return "expected a clarify block (ask_clarification), got none"
    return ""


def _check_artifact(golden: Golden, turn: Turn) -> str:
    artifact_type = golden.get("expect_artifact")
    if not artifact_type:
        return ""
    kinds = [b.get("artifact_type") for b in turn.blocks if b.get("kind") == "artifact"]
    if artifact_type not in kinds:
        return f"expected a '{artifact_type}' artifact block; got {kinds}"
    return ""


def _check_none(golden: Golden, turn: Turn) -> str:
    """None of `expect_none` may appear in anything the user sees: the answer,
    its blocks (artifact rows included) and its provenance (case-insensitive)."""
    seen = " ".join(
        (
            turn.answer,
            json.dumps(turn.blocks, default=str),
            json.dumps(turn.provenance, default=str),
        )
    ).lower()
    leaked = [s for s in golden.get("expect_none", []) if s.lower() in seen]
    if leaked:
        return f"expected none of {leaked} in the answer, blocks or provenance"
    return ""


_CHECKS: list[Callable[[Golden, Turn], str]] = [
    _check_tool,
    _check_metric,
    _check_value,
    _check_any,
    _check_no_numbers,
    _check_clarify,
    _check_artifact,
    _check_none,
]


def _check(golden: Golden, turn: Turn) -> list[str]:
    results = (check(golden, turn) for check in _CHECKS)
    return [failure for failure in results if failure]


def _record(turn: Turn, event: dict[str, Any]) -> None:
    if event["type"] == "tool_status":
        turn.tools_used.append(event["tool"])
    elif event["type"] == "done":
        turn.answer = event["content"]
        turn.provenance = event.get("provenance", [])
        turn.blocks = event.get("blocks", [])
    elif event["type"] in ("error", "blocked"):
        detail = event.get("message") or event.get("reason")
        turn.answer = f"[{event['type']}] {detail}"


EVAL_EMAIL = "evals@yougotagift.com"


# Mirrors the label_class_settings rows migration 0004 seeds.
_DEFAULT_LABEL_MODES: dict[str, tuple[str, int]] = {
    "person_name": ("suppress", 5),
    "business_name": ("pseudonymise", 5),
}


def _grant(
    user: User,
    target_kind: str,
    target: str,
    row_scope: Mapping[str, Sequence[str]] | None = None,
) -> GrantFacts:
    return GrantFacts(
        id=uuid4(),
        subject_type="user",
        subject_id=user.id,
        effect="allow",
        target_kind=target_kind,
        target=target,
        expires_at=None,
        row_scope=row_scope,
    )


def _allow_grant(user: User, entry: str | dict[str, Any]) -> GrantFacts:
    """A plain pattern, or `{pattern, row_scope}` for a row-scoped allow."""
    if isinstance(entry, str):
        return _grant(user, "resource", entry)
    pattern = entry.get("pattern")
    if not isinstance(pattern, str) or set(entry) - {"pattern", "row_scope"}:
        msg = f"allow entry must be a pattern or {{pattern, row_scope}}: {entry!r}"
        raise ValueError(msg)
    row_scope = entry.get("row_scope")
    if row_scope is not None and not _is_row_scope(row_scope):
        msg = f"row_scope must map dimension names to lists of strings: {entry!r}"
        raise ValueError(msg)
    return _grant(user, "resource", pattern, row_scope)


def _is_row_scope(value: object) -> bool:
    """`{dimension: [values]}`, string keys and string values only."""
    if not isinstance(value, dict):
        return False
    items = cast("dict[object, object]", value)
    return all(
        isinstance(dimension, str)
        and isinstance(values, list)
        and all(isinstance(v, str) for v in cast("list[object]", values))
        for dimension, values in items.items()
    )


def _attributes(user: User, golden: Golden) -> dict[str, str]:
    """Golden attributes plus the built-ins, which a golden cannot override."""
    raw = golden.get("attributes", {})
    if not isinstance(raw, dict):
        msg = f"golden {golden.get('id')!r}: attributes must be a mapping"
        raise ValueError(msg)
    items = cast("dict[object, object]", raw).items()
    attributes = {str(k): str(v) for k, v in items}
    attributes.update(email=EVAL_EMAIL, user_id=str(user.id))
    return attributes


def _self_attributes() -> dict[str, str]:
    """dimension -> its `$self` attribute, registry-wide; a dimension declared
    with conflicting attributes is left out (fail closed, like the repository)."""
    declared: dict[str, set[str | None]] = {}
    for _source, _entity, dimension, attribute, _ in get_registry().scope_catalog():
        declared.setdefault(dimension, set()).add(attribute)
    mapping: dict[str, str] = {}
    for dimension, attributes in declared.items():
        only = next(iter(attributes)) if len(attributes) == 1 else None
        if only is not None:
            mapping[dimension] = only
    return mapping


def _label_modes(golden: Golden) -> dict[str, tuple[str, int]]:
    modes = dict(_DEFAULT_LABEL_MODES)
    for label_class, setting in golden.get("label_modes", {}).items():
        if not isinstance(setting, dict) or "mode" not in setting:
            msg = f"golden {golden.get('id')!r}: label_modes.{label_class} needs a mode"
            raise ValueError(msg)
        bucket_size = setting.get("bucket_size", 5)
        if not isinstance(bucket_size, int) or isinstance(bucket_size, bool):
            msg = (
                f"golden {golden.get('id')!r}: label_modes.{label_class} "
                "bucket_size must be an integer"
            )
            raise ValueError(msg)
        modes[label_class] = (setting["mode"], bucket_size)
    return modes


def _policy(user: User, golden: Golden) -> Policy:
    """The eval user sees what the golden allows (default: everything)."""
    grants = [_allow_grant(user, entry) for entry in golden.get("allow", ["*"])]
    grants += [_grant(user, "clearance", c) for c in golden.get("clearances", [])]
    inputs = PolicyInputs(
        user=UserFacts(
            id=user.id, role=user.role, status=user.status, tenant=user.tenant
        ),
        groups={},
        memberships={},
        grants=grants,
        policy_version=0,
        attributes=_attributes(user, golden),
        self_attributes=_self_attributes(),
        label_modes=_label_modes(golden),
    )
    return evaluate(inputs, datetime.now(UTC))


async def _run_question(golden: Golden) -> Turn:
    async with get_session_factory()() as db:
        user = await ensure_service_user(db, EVAL_EMAIL, "Eval runner", "viewer")
        if user.kind != UserKind.SERVICE:
            msg = (
                f"{EVAL_EMAIL} exists as a {user.kind} user, not a service user. "
                "Evals refuse to run as a person; fix or rename that users row."
            )
            raise SystemExit(msg)
        if user.status != UserStatus.ACTIVE:
            msg = (
                f"{EVAL_EMAIL} is {user.status}, not active. "
                "Evals refuse to run as a disabled user; re-enable that users row."
            )
            raise SystemExit(msg)
        session = ChatSession(user_id=user.id, user_email=EVAL_EMAIL)
        db.add(session)
        await db.commit()
        await db.refresh(session)

        caller = AtlasCaller(
            user_id=user.id,
            auth_method="service",
            surface="chat",
            session_id=session.id,
        )
        tools = AtlasTools(caller, _policy(user, golden), db=db)
        turn = Turn()
        async for event in run_chat_turn(tools, golden["question"], [], db):
            _record(turn, event)
        return turn


def _runnable(goldens: list[Golden]) -> list[Golden]:
    """Skip goldens whose metric isn't in the registry (plugin not configured)."""
    registry = get_registry()
    known = set(registry.metrics) | set(registry.funnels)
    runnable = [g for g in goldens if g.get("expect_metric") in (None, *known)]
    skipped = [g["id"] for g in goldens if g not in runnable]
    if skipped:
        print(f"Skipping {len(skipped)} goldens (source not configured): {skipped}")
    return runnable


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--filter", default=None, help="run only goldens whose id contains this"
    )
    args = parser.parse_args()

    settings = get_settings()
    if not (settings.anthropic_api_key or settings.openai_api_key):
        print("No LLM API key set (ANTHROPIC_API_KEY or OPENAI_API_KEY).")
        return 2
    print(f"Provider: {settings.llm_provider} / {settings.resolved_agent_model}")

    goldens = _runnable(_load_goldens(args.filter))
    print(f"Running {len(goldens)} goldens...\n")

    passed = 0
    for golden in goldens:
        turn = await _run_question(golden)
        failures = _check(golden, turn)
        passed += not failures
        print(f"[{'FAIL' if failures else 'PASS'}] {golden['id']}")
        for failure in failures:
            print(f"       - {failure}")
        if failures:
            print(f"       answer: {turn.answer[:300]}")

    print(f"\n{passed}/{len(goldens)} goldens passed")
    return 0 if passed == len(goldens) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
