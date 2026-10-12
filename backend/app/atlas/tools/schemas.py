"""The atlas tool schemas: what models and MCP clients are offered."""

from typing import Any

_DATE_PROPS = {
    "start_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
    "end_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
}

ATLAS_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_metrics",
        "description": "List every governed metric and funnel in the atlas, grouped "
        "by data source, with descriptions. Call this first when unsure what data "
        "exists.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_metric",
        "description": "Get the value of a governed metric. Range metrics require "
        "start_date/end_date (inclusive UTC); snapshot metrics ('as of now') take no "
        "dates. The only sanctioned way to obtain a business number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_id": {
                    "type": "string",
                    "description": "Metric id from list_metrics",
                },
                **_DATE_PROPS,
            },
            "required": ["metric_id"],
        },
    },
    {
        "name": "metric_breakdown",
        "description": "Top-N breakdown of a metric (e.g. top accounts by revenue, "
        "tasks per CSM). Only for metrics where list_metrics shows "
        "has_breakdown=true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_id": {"type": "string"},
                "limit": {
                    "type": "integer",
                    "description": "Rows to return (default 10, max 50)",
                },
                **_DATE_PROPS,
            },
            "required": ["metric_id"],
        },
    },
    {
        "name": "describe_entity",
        "description": "Describe an atlas entity: fields, PII flags, its metrics and "
        "funnels.",
        "input_schema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string"}},
            "required": ["entity_id"],
        },
    },
    {
        "name": "funnel_analyze",
        "description": "Analyze a governed funnel over a date range: step counts, "
        "step conversion, overall conversion, and the biggest drop-off point.",
        "input_schema": {
            "type": "object",
            "properties": {"funnel_id": {"type": "string"}, **_DATE_PROPS},
            "required": ["funnel_id", "start_date", "end_date"],
        },
    },
    {
        "name": "compare_periods",
        "description": "Compare a range metric between two date ranges (e.g. this "
        "month vs last month). Returns both values, absolute delta, and percent "
        "change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_id": {"type": "string"},
                "period_a_start": {"type": "string"},
                "period_a_end": {"type": "string"},
                "period_b_start": {"type": "string"},
                "period_b_end": {"type": "string"},
            },
            "required": [
                "metric_id",
                "period_a_start",
                "period_a_end",
                "period_b_start",
                "period_b_end",
            ],
        },
    },
    {
        "name": "search_atlas",
        "description": "Keyword-search the atlas for entities, metrics, and funnels "
        "matching a topic.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
]
