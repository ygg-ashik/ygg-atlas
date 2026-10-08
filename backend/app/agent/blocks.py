"""Structured answer blocks attached to the `done` event.

- clarify: the agent asks the user to choose instead of guessing (guardrail #1).
- artifact: a table built deterministically from an audited atlas tool result
  (guardrail #2: numbers come from tool output, never from LLM prose).
"""

from collections.abc import Callable
from typing import Any

MAX_CLARIFY_OPTIONS = 4

type Block = dict[str, Any]
type _ArtifactBuilder = Callable[[dict[str, Any], int], Block | None]

CLARIFY_TOOL: dict[str, Any] = {
    "name": "ask_clarification",
    "description": (
        "Ask the user to choose between 2-4 interpretations when the question is "
        "ambiguous or matches several governed metrics/periods, instead of guessing. "
        "Use plain business labels (never internal ids as labels). After calling it, "
        "end your turn with ONE short sentence restating what you need; do not "
        "answer with numbers in the same turn."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The clarifying question to show.",
            },
            "options": {
                "type": "array",
                "minItems": 2,
                "maxItems": MAX_CLARIFY_OPTIONS,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "Business-language choice",
                        },
                        "metric_id": {
                            "type": "string",
                            "description": "Governed metric id this choice maps "
                            "to, if any",
                        },
                    },
                    "required": ["label"],
                },
            },
        },
        "required": ["question", "options"],
    },
}


def _clarify_option(raw: object, known_metric_ids: set[str]) -> Block | None:
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("label") or "").strip()
    if not label:
        return None
    metric_id = raw.get("metric_id")
    return {
        "label": label,
        "metric_id": metric_id if metric_id in known_metric_ids else None,
    }


def build_clarify_block(
    arguments: dict[str, Any], known_metric_ids: set[str]
) -> Block | None:
    """Validate model-supplied clarify arguments.

    Unknown metric ids are dropped (never trusted); at most 4 options are kept.
    """
    question = str(arguments.get("question") or "").strip()
    raw = arguments.get("options")
    candidates: list[object] = list(raw) if isinstance(raw, list) else []
    options = [
        opt
        for opt in (_clarify_option(c, known_metric_ids) for c in candidates)
        if opt is not None
    ][:MAX_CLARIFY_OPTIONS]
    if not question or len(options) < 2:
        return None
    return {"kind": "clarify", "question": question, "options": options}


def _first_provenance(result: dict[str, Any]) -> dict[str, Any] | None:
    prov = result.get("provenance") or []
    return prov[0] if prov else None


def _breakdown(result: dict[str, Any], seq: int) -> Block | None:
    rows = [[r.get("label"), r.get("value")] for r in result.get("rows", [])]
    if not rows:
        return None
    return {
        "id": f"metric_breakdown:{result.get('metric_id')}:{seq}",
        "artifact_type": "breakdown",
        "title": f"{result.get('name')}: breakdown",
        "unit": result.get("unit") or "",
        "columns": ["Label", "Value"],
        "rows": rows,
    }


def _comparison(result: dict[str, Any], seq: int) -> Block | None:
    a = result.get("period_a") or {}
    b = result.get("period_b") or {}
    pct = result.get("delta_pct")
    suffix = f" ({pct:+.1f}%)" if isinstance(pct, int | float) else ""
    return {
        "id": f"compare_periods:{result.get('metric_id')}:{seq}",
        "artifact_type": "comparison",
        "title": f"{result.get('name')}: period comparison{suffix}",
        "unit": result.get("unit") or "",
        "columns": ["Period", "Start", "End", "Value"],
        "rows": [
            ["A", a.get("start"), a.get("end"), a.get("value")],
            ["B", b.get("start"), b.get("end"), b.get("value")],
        ],
    }


def _funnel(result: dict[str, Any], seq: int) -> Block | None:
    steps = result.get("steps") or []
    if not steps:
        return None
    return {
        "id": f"funnel_analyze:{result.get('funnel_id')}:{seq}",
        "artifact_type": "funnel",
        "title": str(result.get("name")),
        "unit": "users",
        "columns": ["Step", "Users", "Conversion from previous %"],
        "rows": [
            [s.get("name"), s.get("count"), s.get("conversion_from_previous_pct")]
            for s in steps
        ],
    }


_BUILDERS: dict[str, _ArtifactBuilder] = {
    "metric_breakdown": _breakdown,
    "compare_periods": _comparison,
    "funnel_analyze": _funnel,
}


def artifact_from_result(tool: str, result: dict[str, Any], seq: int) -> Block | None:
    """Turn a successful table-shaped tool result into an artifact block (or None)."""
    builder = _BUILDERS.get(tool)
    if builder is None or "error" in result:
        return None
    provenance = _first_provenance(result)
    body = builder(result, seq) if provenance is not None else None
    if body is None:
        return None
    return {"kind": "artifact", **body, "provenance": provenance}
