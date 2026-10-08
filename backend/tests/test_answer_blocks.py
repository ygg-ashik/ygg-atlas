"""Structured answer blocks: built from tool arguments/results, never from LLM prose."""

from app.agent.blocks import CLARIFY_TOOL, artifact_from_result, build_clarify_block

PROV = {
    "tool": "metric_breakdown",
    "source": "demo",
    "metric_id": "revenue",
    "metric_name": "Revenue",
    "freshness": None,
    "executed_at": "2026-10-08T00:00:00+00:00",
}


def test_clarify_tool_schema_is_a_valid_tool():
    assert CLARIFY_TOOL["name"] == "ask_clarification"
    props = CLARIFY_TOOL["input_schema"]["properties"]
    assert {"question", "options"} <= set(props)


def test_build_clarify_block_keeps_known_metric_ids_only():
    block = build_clarify_block(
        {
            "question": "Which revenue do you mean?",
            "options": [
                {"label": "Corporate revenue", "metric_id": "b2b_revenue"},
                {"label": "All revenue", "metric_id": "revenue"},
                {"label": "Made up", "metric_id": "not_a_metric"},
            ],
        },
        known_metric_ids={"revenue", "b2b_revenue"},
    )
    assert block == {
        "kind": "clarify",
        "question": "Which revenue do you mean?",
        "options": [
            {"label": "Corporate revenue", "metric_id": "b2b_revenue"},
            {"label": "All revenue", "metric_id": "revenue"},
            {"label": "Made up", "metric_id": None},
        ],
    }


def test_build_clarify_block_rejects_bad_shapes():
    one = {"question": "x", "options": [{"label": "only one"}]}
    assert build_clarify_block(one, set()) is None
    no_question = {"question": "", "options": [{"label": "a"}, {"label": "b"}]}
    assert build_clarify_block(no_question, set()) is None
    many = [{"label": str(i)} for i in range(6)]
    block = build_clarify_block({"question": "Pick", "options": many}, set())
    assert block is not None
    assert len(block["options"]) == 4  # capped at 4
    blank = build_clarify_block(
        {"question": "Pick", "options": [{"label": " "}, {"label": "b"}]}, set()
    )
    assert blank is None  # fewer than 2 usable labels


def test_build_clarify_block_ignores_non_list_and_non_dict_options():
    assert build_clarify_block({"question": "Q", "options": "a,b"}, set()) is None
    mixed = {"question": "Q", "options": ["a", {"label": "b"}, {"label": "c"}]}
    block = build_clarify_block(mixed, set())
    assert block is not None
    assert [o["label"] for o in block["options"]] == ["b", "c"]


def test_breakdown_result_becomes_artifact():
    result = {
        "metric_id": "revenue",
        "name": "Revenue",
        "unit": "AED",
        "rows": [{"label": "b2b", "value": 1000.0}, {"label": "b2c", "value": 500.0}],
        "provenance": [PROV],
    }
    art = artifact_from_result("metric_breakdown", result, seq=1)
    assert art == {
        "kind": "artifact",
        "id": "metric_breakdown:revenue:1",
        "artifact_type": "breakdown",
        "title": "Revenue: breakdown",
        "unit": "AED",
        "columns": ["Label", "Value"],
        "rows": [["b2b", 1000.0], ["b2c", 500.0]],
        "provenance": PROV,
    }


def test_compare_result_becomes_artifact():
    result = {
        "metric_id": "revenue",
        "name": "Revenue",
        "unit": "AED",
        "period_a": {"start": "2026-09-01", "end": "2026-09-30", "value": 120.0},
        "period_b": {"start": "2026-08-01", "end": "2026-08-31", "value": 100.0},
        "delta": 20.0,
        "delta_pct": 20.0,
        "provenance": [PROV],
    }
    art = artifact_from_result("compare_periods", result, seq=2)
    assert art is not None
    assert art["artifact_type"] == "comparison"
    assert art["columns"] == ["Period", "Start", "End", "Value"]
    assert art["rows"] == [
        ["A", "2026-09-01", "2026-09-30", 120.0],
        ["B", "2026-08-01", "2026-08-31", 100.0],
    ]
    assert art["title"] == "Revenue: period comparison (+20.0%)"


def test_compare_without_delta_pct_has_plain_title():
    result = {
        "metric_id": "revenue",
        "name": "Revenue",
        "unit": "AED",
        "period_a": {"start": "2026-09-01", "end": "2026-09-30", "value": 1.0},
        "period_b": {"start": "2026-08-01", "end": "2026-08-31", "value": 0.0},
        "delta_pct": None,
        "provenance": [PROV],
    }
    art = artifact_from_result("compare_periods", result, seq=1)
    assert art is not None
    assert art["title"] == "Revenue: period comparison"


def test_funnel_result_becomes_artifact():
    result = {
        "funnel_id": "checkout_funnel",
        "name": "Checkout funnel",
        "steps": [
            {
                "id": "a",
                "name": "View",
                "count": 100.0,
                "conversion_from_previous_pct": None,
            },
            {
                "id": "b",
                "name": "Cart",
                "count": 60.0,
                "conversion_from_previous_pct": 60.0,
            },
        ],
        "provenance": [PROV],
    }
    art = artifact_from_result("funnel_analyze", result, seq=3)
    assert art is not None
    assert art["artifact_type"] == "funnel"
    assert art["id"] == "funnel_analyze:checkout_funnel:3"
    assert art["columns"] == ["Step", "Users", "Conversion from previous %"]
    assert art["rows"] == [["View", 100.0, None], ["Cart", 60.0, 60.0]]
    assert art["unit"] == "users"


def test_errors_and_other_tools_produce_no_artifact():
    assert artifact_from_result("metric_breakdown", {"error": "boom"}, seq=1) is None
    query = {"value": 1.0, "provenance": [PROV]}
    assert artifact_from_result("query_metric", query, seq=1) is None
    empty = {"name": "x", "rows": [], "provenance": []}
    assert artifact_from_result("metric_breakdown", empty, seq=1) is None
    no_steps = {"name": "f", "steps": [], "provenance": [PROV]}
    assert artifact_from_result("funnel_analyze", no_steps, seq=1) is None
