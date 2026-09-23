# ygg-atlas — MVP Design & North-Star Architecture

**Date:** 2026-09-23 · **Status:** Approved · **Author:** Ashik + Claude (brainstorm + 6-agent research synthesis)

## 1. Vision

ygg-atlas is YouGotAGift's data-intelligence platform: a "neural map / atlas" over every product and service — ecommerce apps, direct customer-facing apps, ads, analytics, campaigns, revenue, and user-event streams. It gathers and curates data from multiple cloud sources, explains user behavior (where corporate clients get stuck, what the resistance points are), measures campaign effectiveness, and (later) optimizes ads budgets — all exposed through an AI chat interface and, in future, an embeddable SDK, with MCP as the connective tissue between data and agents.

**Guiding thesis:** ygg-atlas is not a warehouse with a chatbot on top. It is a governed **semantic layer** (the atlas) exposed to agents via MCP. Three invariants:

1. **Agents never touch raw tables.** Answers come from governed metric/entity definitions, never freeform text-to-SQL (10–50% accuracy on real schemas vs ~98% with semantic grounding). If the atlas can't answer, the agent asks a clarifying question — it never guesses.
2. **Every number carries provenance.** Metric name, source, vetted query, data freshness — shown in the UI on every answer.
3. **Access control is enforced below the model.** Read-only connectors, table allowlists, scope from auth token — never from the prompt.

The "superintelligence" feeling comes from *trusted* answers to arbitrary questions. Trust is built by the semantic layer and evals, not by agent sophistication.

## 2. MVP Scope (v0 — "One trusted answer surface")

- **Data sources:** existing app databases (read replicas, read-only) + GA4 (Data API). No warehouse exists yet; none is built in MVP.
- **Audience:** internal teams only (Firebase auth, domain-locked to `@yougotagift.com`).
- **Surface:** web chat app (React 19 + Vite), SSE streaming, provenance chips, feedback.
- **Intelligence:** thin Claude tool-calling loop over ~6 atlas tools. No MMM, no ads ingestion, no SDK yet.
- **MCP:** the same atlas tools exposed at an MCP endpoint so external MCP clients (Claude Desktop, other agents) can query the atlas.
- **Evals:** golden Q&A suite from day one; merge-blocking in CI later.
- **Hosting:** existing AWS EC2 machine (`ssh atlas`), docker-compose runtime.

### MVP architecture

```
frontend (React19+Vite, SSE chat, provenance chips)
   │ Firebase ID token
backend/ (FastAPI, Python 3.12)
   ├── api/          chat sessions + SSE streaming endpoint
   ├── agent/        thin Claude tool-calling loop + guardrails + rate limits
   ├── atlas/        semantic registry: entities, metrics, funnels as YAML defs
   │                 with vetted SQL/GA4 queries + PII tags
   │                 tools: list_metrics, query_metric, describe_entity,
   │                        funnel_analyze, compare_periods, search_atlas
   ├── connectors/   read-only: app DBs (allowlisted tables), GA4 Data API
   └── mcp/          FastMCP server exposing the SAME atlas tools
Postgres (own DB: sessions, messages, audit log of every agent query)
evals/  golden Q&A suite
```

Atlas tools are defined once in `backend/app/atlas/` and consumed both in-process by the chat agent and via MCP — no drift between surfaces.

### Component standard (enterprise-grade, self-contained)

Every module has one clear purpose, a public interface at its root (`__init__.py` / `index.ts`), no reaching into another feature's internals, downward-only dependency direction (features → api/lib → ui), and is testable in isolation. Frontend enforces boundaries with ESLint `no-restricted-imports`. No legacy silos — the tree stays clean from day one.

## 3. Stack (MVP)

| Layer | Choice | Note |
|---|---|---|
| Frontend | React 19 + Vite + TS, Tailwind + shadcn/ui, TanStack Query | Mirrors atwork_agent_fe; chat components adapted from its assistant feature |
| Backend | FastAPI + SQLModel + Alembic, Python 3.12, uv | Mirrors atwork conventions (UTC/TIMESTAMP rule, structlog) |
| LLM | Claude API (anthropic SDK), thin tool loop | Single agent + tools; no graph framework needed for analytics chat |
| Semantic layer | In-repo YAML registry (v0) | Graduate to Cube Core when multi-tenant SDK arrives |
| MCP | FastMCP (streamable HTTP) | Same tool implementations as the chat agent |
| Auth | Firebase (Google OAuth, `@yougotagift.com` only) | Port of atwork middleware |
| DB | Postgres 16 (docker) | Sessions, messages, audit log |
| Evals | YAML goldens + replay harness | promptfoo/DeepEval-style, CI-gating |
| Deploy | AWS EC2 (`ssh atlas`), docker compose, reverse proxy + HTTPS | Runbook in README |

## 4. North-Star Architecture (roadmap, not MVP)

Layered target state from the research synthesis:

1. **Ingestion:** GA4 → BigQuery native export (enable immediately — not retroactive), Google Ads DTS (free), Airbyte for Meta Ads/CRM long tail, RudderStack OSS for warehouse-first behavioral events, Debezium → Redpanda CDC for order/revenue OLTP, server-side conversion relay (Meta CAPI + Google Enhanced Conversions, consent-gated).
2. **Storage & transform:** BigQuery center of gravity + Iceberg on GCS (lock-in escape hatch), dbt Core medallion (bronze → silver conformed entities + identity graph → gold metric marts), Dagster asset orchestration (lineage graph feeds the atlas), ClickHouse hot tier for sub-second funnels.
3. **Semantic/ontology (the atlas):** typed objects (Customer, GiftCard, Order, Campaign, CorporateClient, FunnelStage) + links + PII tags; Cube Core for served metrics with compile-time row-level security; **identity graph with buyer≠recipient gift-link edges** — YGG's hardest and most differentiating domain problem; mislinking corrupts LTV/attribution forever.
4. **Intelligence:** PyMC-Marketing MMM (monthly refit) + geo-lift experiment registry + marginal-ROAS budget allocator; funnel/journey engine; anomaly monitors that feed chat proactively.
5. **MCP plane:** one in-house atlas MCP server (stateless, OAuth 2.1+PKCE, ~12 workflow-shaped tools); federate official Google/Meta ads MCP servers behind the same auth; gateway only at 3+ servers. The only door to data.
6. **Surfaces:** chat app, iframe widget + <5KB loader, `@ygg-atlas/sdk-react`; short-lived tenant JWTs; corporate clients get the same agent scoped to their own data.

### Phased roadmap

- **Phase 0 (now, zero code):** enable GA4 → BigQuery export + Google Ads DTS. Every day waited is history lost.
- **MVP (this spec):** chat over app DBs + GA4 with semantic registry, provenance, evals, MCP endpoint.
- **v1:** warehouse + dbt medallion, ads ingestion, MMM + first geo-lift experiment, ClickHouse/PostHog funnel→replay loop, embeddable widget + tenant RLS.
- **Future ("ads command center"):** ads write-tools behind approval gates and MMM-derived spend envelopes; progressive autonomy ladder (propose → execute-with-notification → autonomous within caps), promoted per-action on eval evidence.

### The 5 "wow" capabilities (target)

1. **Truth-over-platform-ROAS** — "Meta reports 3.2; our geo-tested incrementality says ~1.1" with credible intervals.
2. **Counterfactual budget scenarios in chat** — "move $50k from Meta to Google Search?" answered from saturation curves, executed only with human approval.
3. **Root-cause funnel forensics with evidence** — which segment drops, what predicts it, linked session replays, joined to CRM stage for B2B clients.
4. **The living atlas** — lineage + freshness answered inline: "where does this number come from?"
5. **Embedded corporate-client intelligence** — clients query their own scoped data via SDK/MCP; the gift-link identity graph makes answers correct where off-the-shelf CDPs are wrong.

## 5. Top pitfalls (bake into reviews)

1. Raw text-to-SQL as primary path — silent, confident fabrication.
2. Skipping GA4 export or the identity graph — irreversible data loss / unanswerable attribution.
3. Tenant/scope leakage below the model — caches keyed on tenant + freshness; scope from token only.
4. Trusting platform ROAS or building an MTA engine — triangulate with MMM + experiments instead.
5. LLM write access to ad platforms without hard gates.
6. Shipping agents before evals — merge-blocking goldens from day one.
7. Serving interactive chat straight from heavy analytical queries — pre-aggregate; never hit production OLTP for funnels.
8. Cost blowups — bounded agent loops, per-user budgets, prompt caching.
9. Metric duplication / tool sprawl — one metric layer, ≤15 curated tools.
10. Compliance as retrofit — UAE PDPL: PII region-pinning and pseudonymization are architectural, not add-ons.

## 6. Verification (MVP definition of done)

- Backend pytest >80% coverage on new code; frontend vitest green; lint/typecheck clean both sides.
- Golden question ("What was revenue last week?" on seeded data) answered via streaming with provenance chip (metric, source, freshness).
- Out-of-registry question → clarifying question, not invented numbers.
- MCP client can call `list_metrics` on the `/mcp` endpoint.
- `evals/run_evals.py` passes all goldens.
- Deployed on the EC2 box (`ssh atlas`) and answering over HTTPS.
