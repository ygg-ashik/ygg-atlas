"""Golden-suite replay harness for the ygg-atlas agent.

Runs each golden question through the real agent loop (the configured LLM provider
and the seeded demo data) and checks tool usage, provenance and answer content.

Usage (from backend/, so the installed `app` package and its venv are used):
    uv run python ../evals/run_evals.py [--filter SUBSTRING]

Requires: an LLM key (OPENAI_API_KEY or ANTHROPIC_API_KEY), seeded demo data
(uv run python scripts/seed_demo.py), and the ygg-atlas database per backend/.env.
"""

import argparse
import asyncio
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from app.agent.loop import run_chat_turn
from app.atlas.registry import get_registry
from app.config import get_settings
from app.database import get_session_factory
from app.models.chat import ChatSession

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


def _check_tool(golden: Golden, _answer: str, tools: list[str], _p: Provenance) -> str:
    tool = golden.get("expect_tool")
    if tool and tool not in tools:
        return f"expected tool '{tool}' to run; used {tools}"
    return ""


def _check_metric(golden: Golden, _answer: str, _t: list[str], prov: Provenance) -> str:
    metric = golden.get("expect_metric")
    metric_ids = {p.get("metric_id") for p in prov}
    if metric and metric not in metric_ids:
        return f"expected metric '{metric}' in provenance; got {metric_ids}"
    return ""


def _check_value(golden: Golden, answer: str, _t: list[str], _p: Provenance) -> str:
    value = golden.get("expect_value")
    if value is not None and not any(v in answer for v in _fmt_variants(value)):
        return f"expected value {value} in answer"
    return ""


def _check_any(golden: Golden, answer: str, _t: list[str], _p: Provenance) -> str:
    any_of = golden.get("expect_any")
    if any_of and not any(s.lower() in answer.lower() for s in any_of):
        return f"expected one of {any_of} in answer"
    return ""


def _check_no_numbers(
    golden: Golden, answer: str, _t: list[str], _p: Provenance
) -> str:
    if not golden.get("expect_no_numbers"):
        return ""
    numbers = set(re.findall(r"\d[\d,\.]*", answer)) - _INNOCENT_NUMBERS
    if numbers:
        return f"expected no data numbers, found {sorted(numbers)[:5]}"
    return ""


_CHECKS: list[Callable[[Golden, str, list[str], Provenance], str]] = [
    _check_tool,
    _check_metric,
    _check_value,
    _check_any,
    _check_no_numbers,
]


def _check(
    golden: Golden, answer: str, tools_used: list[str], provenance: Provenance
) -> list[str]:
    results = (check(golden, answer, tools_used, provenance) for check in _CHECKS)
    return [failure for failure in results if failure]


async def _run_question(question: str) -> tuple[str, list[str], Provenance]:
    async with get_session_factory()() as db:
        session = ChatSession(
            user_uid="eval-runner", user_email="evals@yougotagift.com"
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)

        answer, tools_used, provenance = "", [], []
        async for event in run_chat_turn("eval-runner", session.id, question, [], db):
            if event["type"] == "tool_status":
                tools_used.append(event["tool"])
            elif event["type"] == "done":
                answer = event["content"]
                provenance = event.get("provenance", [])
            elif event["type"] in ("error", "blocked"):
                detail = event.get("message") or event.get("reason")
                answer = f"[{event['type']}] {detail}"
        return answer, tools_used, provenance


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
        answer, tools_used, provenance = await _run_question(golden["question"])
        failures = _check(golden, answer, tools_used, provenance)
        passed += not failures
        print(f"[{'FAIL' if failures else 'PASS'}] {golden['id']}")
        for failure in failures:
            print(f"       - {failure}")
        if failures:
            print(f"       answer: {answer[:300]}")

    print(f"\n{passed}/{len(goldens)} goldens passed")
    return 0 if passed == len(goldens) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
