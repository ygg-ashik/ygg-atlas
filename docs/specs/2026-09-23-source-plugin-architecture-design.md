# Source Plugin Architecture + DeepSales Plugin

**Date:** 2026-09-23 · **Status:** Approved · **Depends on:** MVP design (same date), `docs/data-models/deepsales.md`

## Goal

ygg-atlas will connect many data sources (ecom DB, DeepSales, GA4, ads platforms). Each source
must be a **self-contained plugin**: its own config, connector, semantic definitions, and tests —
discoverable by the atlas kernel without touching kernel code. First real plugin: the DeepSales
DB (`DEEPSALES_DB_URL_LIVE`).

## Architecture

```
backend/app/
├── atlas/                 # KERNEL (source-agnostic): registry, tools, provenance, models
└── sources/               # PLUGINS — one self-contained package per source
    ├── __init__.py        # discover(): iterate subpackages → SourcePlugin registry
    ├── base.py            # SourcePlugin contract + SQLSourceConnector (SELECT-only) + errors
    ├── demo/              #   manifest.py (SOURCE), connector via APPDB_URL, definitions/, seed.py
    ├── ga4/               #   GA4 Data API connector; enabled iff GA4_PROPERTY_ID set
    └── deepsales/         #   DEEPSALES_DB_URL_LIVE; definitions for portfolio/revenue/tasks/leads
```

`app/connectors/` is removed; its logic moves into `sources/base.py` (SQL, SELECT-only
enforcement) and `sources/ga4/`.

### Plugin contract (`sources/base.py`)

`SourcePlugin`: `id`, `name`, `description`, `required_env: list[str]`,
`is_configured() -> bool` (its own pydantic Settings reading ONLY its env keys),
`connector() -> Connector` (cached), `definitions_dir: Path`,
`allowed_tables: set[str] | None` (None = non-SQL source, table lint skipped).
Each plugin package exposes `SOURCE: SourcePlugin` from its `manifest.py`.
Unconfigured plugins are skipped at startup with a structured log — never crash the app.

### Kernel changes

- **Registry** loads definitions from every enabled plugin; entity `source` = plugin id
  (YAML `source:` field dropped). **Load-time validation:** metric/funnel/entity ids globally
  unique; every SQL query references only the plugin's `allowed_tables` (regex on FROM/JOIN);
  breakdown queries validated the same way.
- **MetricDef** gains `time_scope: 'range' | 'snapshot'` (default range) and optional
  `breakdown_query` (returns `label`,`value` rows, must use `:limit`; range-scoped breakdowns
  also use `:start`/`:end`).
- **Tools:** `query_metric` dates become optional — required for range metrics (clear error
  otherwise), ignored for snapshot metrics (result carries `as_of` instead). New 7th tool
  `metric_breakdown(metric_id, limit=10, start_date?, end_date?)`. `list_metrics` groups
  output by source with source descriptions. `compare_periods` rejects snapshot metrics.
- **MCP** exposes `metric_breakdown` too (same implementations, no drift).

### DeepSales plugin (v1 definitions — validated against live data 2026-09-23)

Env: `DEEPSALES_DB_URL_LIVE`. Allowed tables: `account_profiles`, `corporate`,
`corporate_revenue_monthly`, `tasks`, `leads`, `csm`.
Live-data facts baked in: `health_v2_status` ∈ Green/Yellow/Red/NULL (NULL = not yet scored;
2,553 of 6,047 profiles analyzed); `product` codes are `AW`/`REW`; `corporate_sentiment_daily`
is empty → at-risk = `health_v2_status = 'Red'` only (no sentiment join yet); task statuses
seen: pending/in_progress/completed/cancelled; lead stages currently new/contacted/qualified.

- **ds_account** (entity, snapshot metrics over `account_profiles WHERE analyzed_at IS NOT NULL`):
  `ds_total_accounts` (+ breakdown by health_v2_status), `ds_at_risk_accounts` (Red),
  `ds_portfolio_revenue_ytd` (SUM revenue_ytd, breakdown top accounts by revenue_ytd),
  `ds_avg_order_value`, `ds_avg_active_rate`.
- **ds_revenue** (range metrics over `corporate_revenue_monthly`, months intersecting range):
  `ds_revenue_aed` (breakdown top corporates via JOIN corporate), `ds_transactions`.
- **ds_tasks**: snapshot `ds_open_tasks` (pending|in_progress|blocked; breakdown per
  assignee_name — CSM names allowed per PII policy), `ds_overdue_tasks`; range
  `ds_tasks_created` (created_at), `ds_tasks_completed` (status=completed by updated_at,
  approximation documented).
- **ds_leads**: funnel `ds_lead_funnel` on created_at cohort — created → contacted
  (stage≠new) → qualified (qualified|won) → won; cumulative-stage caveat in description.
  Range metric `ds_leads_created`.
- PII: no query selects emails/phones/contact fields; `assignee_name`/`csm_name` permitted.

### Security

`DEEPSALES_DB_URL_LIVE` is currently the postgres superuser — **interim** guard is the
connector's SELECT-only + single-statement enforcement; plugin README and a startup warning
demand a `SELECT`-only role swap. (Decision: proceed now, request RO role.)

### Testing & evals

- Kernel: plugin discovery (configured/unconfigured), id-collision + table-lint validation
  errors, snapshot vs range date rules, metric_breakdown, compare_periods snapshot rejection.
- Demo plugin keeps all existing golden/tests (source id renames `appdb` → `demo`).
- DeepSales: definitions load + lint test (no live DB needed); optional live smoke test skipped
  unless `DEEPSALES_DB_URL_LIVE` is set.
- Evals: +6 structural DeepSales goldens (right tool + right metric + honest phrasing; no exact
  values — live data moves).

### Out of scope (explicit)

Product-code filters (AW/REW) as metric parameters, sentiment-based at-risk (table empty),
pipeline value metrics (mixed currencies), GA4 metric definitions (connector ships, definitions
when GA4 is configured), pip entry-point plugin loading (graduation path when SDK ships).

## Verification

Backend tests green (incl. new kernel/plugin tests), ruff clean. On the EC2 box with the live
URL: chat answers "How many accounts are at risk?" via `ds_at_risk_accounts` with provenance
`deepsales`; "top 5 accounts by revenue" via metric_breakdown; evals (demo + deepsales
goldens) pass; MCP tools/list shows 7 tools.
