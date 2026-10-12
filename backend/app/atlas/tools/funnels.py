"""The funnel tool: funnel_analyze.

It authorises the funnel, compiles the caller's row scope into every step
before running any of them, and returns the steps with provenance.
"""

from typing import Any

from app.atlas.policy import funnel_resource
from app.atlas.provenance import build_provenance, provenance_scope
from app.atlas.tools.dates import range_params
from app.atlas.tools.door import AtlasDoor, Compile, Freshness, connector
from app.atlas.tools.errors import AtlasToolError


class FunnelTools:
    """Governed funnel analysis for one caller."""

    def __init__(
        self, door: AtlasDoor, *, compile_sql: Compile, freshness: Freshness
    ) -> None:
        self._door = door
        self._compile = compile_sql
        self._freshness = freshness

    async def funnel_analyze(
        self, funnel_id: str, start_date: str, end_date: str
    ) -> dict[str, Any]:
        registry = self._door.registry
        funnel = registry.funnels.get(funnel_id)
        if funnel is None:
            raise AtlasToolError(
                f"No funnel '{funnel_id}' in the atlas. Use list_metrics."
            )
        entity = registry.entities.get(funnel.entity)
        scope = self._door.authorize(funnel_resource(funnel), funnel.name, entity)
        params = range_params(start_date, end_date)
        compiled_steps = [
            (step, self._compile(step.query, entity, scope, funnel.name))
            for step in funnel.steps
        ]
        source = connector(funnel.source)

        steps: list[dict[str, Any]] = []
        prev_count: float | None = None
        worst: dict[str, Any] = {"step": None, "drop_pct": 0.0}
        for step, compiled in compiled_steps:
            row = await source.fetch_one(compiled.sql, params | compiled.params)
            count = float(row.get("value", 0) if row else 0)
            conversion = (count / prev_count * 100) if prev_count else None
            if conversion is not None:
                drop = 100 - conversion
                if drop > worst["drop_pct"]:
                    worst = {"step": step.name, "drop_pct": round(drop, 1)}
            steps.append(
                {
                    "id": step.id,
                    "name": step.name,
                    "count": count,
                    "conversion_from_previous_pct": round(conversion, 1)
                    if conversion is not None
                    else None,
                }
            )
            prev_count = count if count > 0 else prev_count

        overall = (
            round(steps[-1]["count"] / steps[0]["count"] * 100, 1)
            if steps and steps[0]["count"]
            else None
        )
        return {
            "funnel_id": funnel.id,
            "name": funnel.name,
            "start_date": start_date,
            "end_date": end_date,
            "steps": steps,
            "overall_conversion_pct": overall,
            "biggest_drop": worst,
            "provenance": [
                build_provenance(
                    "funnel_analyze",
                    funnel.source,
                    metric_id=funnel.id,
                    metric_name=funnel.name,
                    freshness=await self._freshness(entity, scope),
                    scope=provenance_scope(scope),
                )
            ],
        }
