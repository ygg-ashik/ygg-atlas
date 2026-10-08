"""GA4 Data API connector.

The registry defines GA4 'queries' as a compact spec string:
    "metric=<ga4Metric>[;dimensionFilter=<field>==<value>]"
executed as a RunReport for the requested date range. Requires
GA4_PROPERTY_ID and GOOGLE_APPLICATION_CREDENTIALS to be configured.
"""

from typing import Any

from app.sources.base import ConnectorError, ConnectorNotConfiguredError
from app.sources.ga4.manifest import GA4Settings


def _parse_spec(spec: str) -> dict[str, str]:
    parts = [p.strip() for p in spec.strip().split(";") if p.strip()]
    parsed: dict[str, str] = {}
    for part in parts:
        key, _, value = part.partition("=")
        parsed[key.strip()] = value.strip()
    if "metric" not in parsed:
        raise ConnectorError(f"Invalid GA4 query spec: {spec!r}")
    return parsed


class GA4Connector:
    key = "ga4"

    async def fetch_one(
        self, query: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        settings = GA4Settings()
        if not settings.ga4_property_id:
            raise ConnectorNotConfiguredError(
                "GA4 is not configured yet (GA4_PROPERTY_ID missing). "
                "Tell the user this source is pending setup."
            )
        spec = _parse_spec(query)
        try:
            # Optional dependency: only present with the 'ga4' extra installed.
            from google.analytics.data_v1beta import (  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
                BetaAnalyticsDataClient,
            )
            from google.analytics.data_v1beta.types import (  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
                DateRange,
                Filter,
                FilterExpression,
                Metric,
                RunReportRequest,
            )
        except ImportError as exc:
            raise ConnectorNotConfiguredError(
                "google-analytics-data is not installed (install the 'ga4' extra)"
            ) from exc

        request = RunReportRequest(
            property=f"properties/{settings.ga4_property_id}",
            metrics=[Metric(name=spec["metric"])],
            date_ranges=[
                DateRange(
                    start_date=str(params["start"])[:10],
                    end_date=str(params["end"])[:10],
                )
            ],
        )
        if "dimensionFilter" in spec:
            field, _, value = spec["dimensionFilter"].partition("==")
            request.dimension_filter = FilterExpression(
                filter=Filter(
                    field_name=field.strip(),
                    string_filter=Filter.StringFilter(value=value.strip()),
                )
            )

        client = BetaAnalyticsDataClient()
        response = client.run_report(request)
        value = response.rows[0].metric_values[0].value if response.rows else 0
        return {"value": float(value)}

    async def fetch_all(
        self, query: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        raise ConnectorError("GA4 breakdowns are not supported yet")
