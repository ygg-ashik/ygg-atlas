---
name: production-code-review
description: MANDATORY before declaring any coding task in ygg-atlas complete, before committing, and before opening a PR; also use when asked to review a diff or branch. Reviews the change as a production architect (architecture, boundaries, coupling, naming, duplication, complexity, error handling, security and guardrails, typing, tests, observability, performance, API and component boundaries) after confirming `make check` is green, and returns a PASS / PASS WITH WARNINGS / FAIL verdict with file:line evidence.
---

# Production code review

You are reviewing, not writing. Judge the change against `ARCHITECTURE.md`, `CLAUDE.md` (guardrails,
datetime rule, quality gates) and `DESIGN.md` for UI. Tools already police formatting and lint
rules, so do not repeat them; look for what tools cannot see.

## Procedure

1. **Scope the change.** `git diff --stat <base>...HEAD` and `git diff <base>...HEAD` (base is
   usually `main`). Include uncommitted work with `git diff`. List every file touched.
2. **Run the gate.** `make check` from the repo root. If it fails, the verdict is **FAIL**: report
   the failing step and stop the review there.
3. **Review each dimension** below. Every finding cites `file:line`, says why it matters, and
   gives the concrete fix.
4. **Decide the verdict** and output the report in the format at the end.

## Dimensions and what to check

| Dimension | Checks |
|---|---|
| Architecture and ownership | Each new file sits where `ARCHITECTURE.md` §2.3 / §3 / the engineering-standards tables put it. New top-level packages have import-linter contracts |
| Dependency boundaries | Routers never import repositories or ORM; features never import features; `ui/` stays pure; no upward imports even where a contract doesn't exist yet |
| Coupling | Modules talk through public interfaces (`__init__.py`, `index.ts`), not internals. No new shared mutable state |
| Naming | Names say what things are in business terms; no `utils`, `helpers`, `manager2`, `data`, `tmp` |
| Duplication | Logic or UI that already exists elsewhere (search for it). Copy-paste across modules |
| Complexity | Functions or components doing several jobs; classes approaching a responsibility limit; deep nesting hidden from linters by extraction into one long helper |
| Error handling | Fail closed. No swallowed exceptions; expected errors become typed results or HTTP errors with business-language messages; nothing leaks internals to users |
| Security and guardrails | No raw text-to-SQL or model-authored queries against sources; bind parameters only; provenance on every number; no raw PII; scope from the token never the prompt; secrets never logged or committed; read-only connectors |
| Typing | Real types instead of `Any`/`any`, Protocols at seams, no unexplained suppressions |
| Tests | A failing-first test exists for new behavior; tests assert behavior not implementation; edge and failure paths covered; no weakened or skipped tests; goldens added for agent/prompt/registry behavior |
| Observability | Meaningful `structlog` events at decision points; every atlas tool execution audited; no `print` |
| Performance | Production-replica queries are cheap (filters, limits, no unbounded joins); no N+1; no blocking calls in async code; streaming stays streaming |
| API boundaries | Pydantic schemas separate from SQLModel tables; no DB model returned raw; backwards-compatible SSE and REST shapes or a documented change |
| Frontend boundaries | Thin pages; data via hooks; tokens from `DESIGN.md`; light, dark, reduced-motion and reduced-transparency considered |
| Datetimes | Every stored datetime is UTC with `TIMESTAMP(timezone=True)` |

## Verdicts

- **FAIL**: `make check` is red, or any finding is blocking (a guardrail or security violation, a
  broken layer boundary, missing tests for new behavior, data loss risk).
- **PASS WITH WARNINGS**: no blockers, but there are improvements worth tracking (e.g. a service
  approaching its responsibility limit).
- **PASS**: no blockers, no meaningful warnings.

## Report format

```
VERDICT: PASS | PASS WITH WARNINGS | FAIL
make check: green | red (<failing step>)

| Dimension               | Result |
|-------------------------|--------|
| Architecture            | PASS   |
| Dependency boundaries   | PASS   |
| Coupling                | PASS   |
| Naming                  | PASS   |
| Duplication             | PASS   |
| Complexity              | WARN   |
| Error handling          | PASS   |
| Security and guardrails | PASS   |
| Typing                  | PASS   |
| Tests                   | PASS   |
| Observability           | PASS   |
| Performance             | PASS   |
| API boundaries          | PASS   |
| Frontend boundaries     | N/A    |

Findings
1. [blocking|warning] path/to/file.py:42 — what is wrong, why it matters. Fix: concrete change.
```

Be specific and evidence-based. Do not pad the report with praise or with issues the linters
already enforce.
