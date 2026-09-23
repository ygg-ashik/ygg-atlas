"""Golden-suite replay harness for the ygg-atlas agent.

Runs each golden question through the real agent loop (real Claude API, seeded
demo data) and checks tool usage, provenance, and answer content.

Usage (from backend/, so the app package and its venv are available):
    uv run python ../evals/run_evals.py [--filter SUBSTRING]

Requires: ANTHROPIC_API_KEY, seeded demo data (uv run python scripts/seed_demo.py),
and the ygg-atlas database reachable per backend/.env.
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path
from uuid import uuid4

import yaml

GOLDENS_DIR = Path(__file__).parent / "goldens"

# Numbers that may legitimately appear in prose without being data claims.
_INNOCENT_NUMBERS = {"1", "2", "3", "7", "24", "30", "90", "100", "2025", "2026"}


def _load_goldens(filter_substr: str | None) -> list[dict]:
    goldens: list[dict] = []
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


def _check(golden: dict, answer: str, tools_used: list[str], provenance: list[dict]) -> list[str]:
    failures: list[str] = []
    answer_lower = answer.lower()

    if tool := golden.get("expect_tool"):
        if tool not in tools_used:
            failures.append(f"expected tool '{tool}' to run; used {tools_used}")

    if metric := golden.get("expect_metric"):
        metric_ids = {p.get("metric_id") for p in provenance}
        if metric not in metric_ids:
            failures.append(f"expected metric '{metric}' in provenance; got {metric_ids}")

    if (value := golden.get("expect_value")) is not None:
        if not any(v in answer for v in _fmt_variants(value)):
            failures.append(f"expected value {value} in answer")

    if any_of := golden.get("expect_any"):
        if not any(s.lower() in answer_lower for s in any_of):
            failures.append(f"expected one of {any_of} in answer")

    if golden.get("expect_no_numbers"):
        numbers = set(re.findall(r"\d[\d,\.]*", answer)) - _INNOCENT_NUMBERS
        if numbers:
            failures.append(f"expected no data numbers, found {sorted(numbers)[:5]}")

    return failures


async def _run_question(question: str) -> tuple[str, list[str], list[dict]]:
    from app.agent.loop import run_chat_turn
    from app.database import get_session_factory
    from app.models.chat import ChatSession

    async with get_session_factory()() as db:
        session = ChatSession(user_uid="eval-runner", user_email="evals@yougotagift.com")
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
                answer = f"[{event['type']}] {event.get('message') or event.get('reason')}"
        return answer, tools_used, provenance


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter", default=None, help="run only goldens whose id contains this")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
    from app.config import get_settings

    settings = get_settings()
    if not (settings.anthropic_api_key or settings.openai_api_key):
        print("No LLM API key set (ANTHROPIC_API_KEY or OPENAI_API_KEY) — cannot run evals.")
        return 2
    print(f"Provider: {settings.llm_provider} / {settings.resolved_agent_model}")

    goldens = _load_goldens(args.filter)
    print(f"Running {len(goldens)} goldens...\n")

    passed = 0
    for golden in goldens:
        answer, tools_used, provenance = await _run_question(golden["question"])
        failures = _check(golden, answer, tools_used, provenance)
        status = "PASS" if not failures else "FAIL"
        passed += not failures
        print(f"[{status}] {golden['id']}")
        if failures:
            for f in failures:
                print(f"       - {f}")
            print(f"       answer: {answer[:300]}")

    print(f"\n{passed}/{len(goldens)} goldens passed")
    return 0 if passed == len(goldens) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
