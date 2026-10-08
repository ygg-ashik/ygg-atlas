# EMAPI data discovery (2026-09-29)

Discovery of four EMAPI production databases to decide which should become atlas source
plugins and which features to build. Everything here was produced by multi-agent workflows
with adversarial critique loops, and is kept so nobody has to re-run (or re-pay for) the analysis.

**Start with [`REPORT.md`](REPORT.md).** It is the decision report: executive summary, data
landscape, hypothesis catalog, feature catalog with priority scores, plugin recommendations
and roadmap. [`GRANTS.md`](GRANTS.md) is the DBA-ready read-only grant request.

## Databases in scope

| Database | Tables | Access for this analysis | Evidence depth |
|---|---|---|---|
| `ygag_ecom_users_db` | 40 | SELECT on all tables | data (VALIDATED) |
| `ygag_ecom_orders_db` | 159 | none | metadata only (STRUCTURAL) |
| `ygag_ecomweb_stores_db` | 134 | none | metadata only (STRUCTURAL) |
| `ygag_emapi_stores_db` | 84 | none | metadata only (STRUCTURAL) |

Access was measured with `has_table_privilege` on 2026-09-29. Findings about the three
unreadable databases come from schema, constraints, row estimates, index sizes and query
statistics. Hypotheses that need their data are labelled NEEDS-GRANT.

## Evidence labels

- **VALIDATED**: backed by a data query that was actually run; the SQL is in the file's provenance appendix.
- **STRUCTURAL**: inferred from schema or metadata only.
- **NEEDS-GRANT**: needs data the analysis role could not read; the exact tables and columns are named.

## Contents

| Path | What it is |
|---|---|
| `EMAPI-Data-Discovery-Report.pdf` | Decision report with the grant request as Appendix A, typeset for review (65 pages) |
| `EMAPI-Data-Discovery-Evidence-Pack.pdf` | All seven theme analyses and seven database profiles with SQL provenance |
| `REPORT.md` | Decision report source (the thing to review) |
| `GRANTS.md` | Consolidated grant request: read-only role, PII-safe views, hashing, per-table grants |
| `profiles/` | One critiqued profile per analysis unit: `users`, `orders-funnel`, `orders-customer-catalog`, `orders-integrations`, `ecomweb-stores`, `emapi-stores`, plus `cross-db` (identity map and end-to-end user journey) |
| `themes/` | Seven theme analyses with insights, hypotheses, features and plugin notes: user lifecycle, purchase friction, gifting and referral network, campaigns and triggers, errors and system behavior, catalog and brand intelligence, risk and fraud |
| `critiques/` | Critic scores and unresolved issues per unit, round by round |
| `tools/` | The read-only query tool and the PDF builder (see below) |

Every profile and theme passed its critic at 8/10 or higher; the per-round history is in each file's
critique record and in `critiques/`.

## How the data was queried

Source databases are IP-restricted and reachable **only from the atlas EC2 box** (`ssh atlas`).

- `tools/atlasq.sh <db> [max_rows]` (laptop side, SQL on stdin) forwards over SSH to
  `tools/atlasq` on the box, which runs `tools/q.py` inside the ygg-atlas backend image.
- `q.py` enforces: single statement; SELECT / WITH / EXPLAIN only; write, DDL and admin keywords
  rejected (including inside CTEs and `EXPLAIN ANALYZE`); a READ ONLY transaction that is always
  rolled back; `statement_timeout` 20s; `lock_timeout` 2s; a server-side cursor capped at 500 rows;
  emails and phone numbers redacted in output.
- Credentials are read at runtime from `~/ygg-atlas/backend/.env` on the box
  (`EMAPI_SHARED_DB_URL`, `EMAPI_SHARED_DB_USERNAME`, `EMAPI_SHARED_DB_PASWWORD`). None are stored here.
- The endpoint is the Aurora reader (`pg_is_in_recovery() = true`).

To deploy the tool on the box again: copy `tools/q.py` and `tools/atlasq` to `~/atlas-analysis/`
and `chmod +x ~/atlas-analysis/atlasq`.

## Rebuilding the PDFs

The report PDF is `REPORT.md` followed by `GRANTS.md` as Appendix A (headings demoted one level).
The evidence pack is the seven `themes/` files then the seven `profiles/` files, one chapter each.

```bash
cd docs/discovery/2026-09-29-emapi
uv run --no-project --with markdown python tools/build_pdf.py <combined>.md EMAPI-Data-Discovery-Report.pdf \
  --title "EMAPI Data Discovery" --subtitle "Which databases become atlas plugins, which features to build, and the hypotheses to test"
```

The builder typesets Markdown to print HTML (cover, contents, evidence-label chips, unbreakable ids)
and renders it with headless Chrome. It deletes nothing; remove the intermediate `.html` afterwards.

## Redactions in this copy

The production login role name is replaced by `<emapi_login_role>` everywhere in this folder.
