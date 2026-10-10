# Auth phase 4 (MCP authentication): progress checkpoint

Branch `feature/auth-mcp`, worktree `.claude/worktrees/p4-mcp-auth`, based on origin/main `ac8ba38`.
Plan: `docs/plans/2026-10-09-auth-rbac-phase-4-mcp-auth.md`.

Durable inputs are in `.claude/handoff/auth-p345/`:
- `brief.md`, `contracts.md` (binding) and `phase4-analysis.md`;
- `p4-rules.md`, which holds the rulings, as-built notes and every "Task N MUST" item;
- `p4-followups.md`, which holds open findings and accepted risks.

Nothing is pushed. No PR has been opened.

## Done tasks

Every task below passed the two-stage review (spec, then quality and security). Every commit is signed.

| Task | Commits |
|---|---|
| Plan | `49e249d` |
| 1 Config, carriers | `69e5193` |
| 2 Models, migration 0005 | `9ff619c` |
| 3 PATs, service tokens, bearer door, access hooks | `bc2d9f9`, then the fix `f81b461` |
| 4 OAuth service | `d253323`, then the fix `d5aaae8` (family lock, client-first lock order, canonical redirects, no raw DB errors) |
| 5 SDK adapters, OAuth routes | `859e8cb` |
| 7 Rate limiting | `efaf4c2` |
| 8 Self-service, consent and admin APIs, `/meta/auth-methods` | `cbf6fb2`, then the fix `2058289` |
| 9 CLI | `743d1fc` |
| 10 Consent page | `1d15fab` |
| 11 nginx, `.env.example`, README, ARCHITECTURE, spec deltas | `1199b7a` |
| 6 MCP server rewrite and wiring (includes its review-fix round) | `d7b7068` |

Notes on the review status:
- **Task 6:** approved on code. The reviewer's final targeted pytest run was cut off by the pause. The implementer's full gate on the same content was green.
- **`d5aaae8`:** its last round (lock order and DB-error mapping) was checked by the orchestrator, not by a separate reviewer.

## Status at 2026-10-10 (resume after usage-limit pause)

- `fe25a89` test(mcp): OAuth smoke script. Two review rounds, then rebuilt from WIP `43aa0fe`.
  It is signed.
- **Staged, not committed (SIGNING_FAILED):** "fix(identity): race-safe OAuth revokes, transient
  failures as server_error". This covers the independent review of `d5aaae8` and the final-review
  fixes. 14 backend files, re-reviewed PASS WITH WARNINGS, and the warnings are fixed. The patch is
  saved in the scratchpad as `identity-fix.patch`. 1Password signing failed six times
  ("failed to fill whole buffer" / "agent returned an error"). It was never bypassed.
- **Unstaged:** plan "As built" additions (mcp:use audit deviation, Task 4 re-review, Task 12),
  an ARCHITECTURE §6 debt row, and this file.
- **Stack on phase 3:** resolved as a no-commit merge preview in `.claude/worktrees/p4-integ`
  (resolved files and the full diff are saved in the scratchpad). Audit columns are scope, masking,
  token_id, client_id. 0005 `down_revision="0004"`, with the chain comment removed. Startup order
  is sync_scope_dimensions, prepare_access, prepare_mcp_auth, then the pseudonym check. The
  strict list is the union. The rebase itself is blocked until signing works, because every
  rebased commit must be signed.
- **CLAUDE.md guardrail-4 sentence (user-approved):** to be its own commit after the rebase.

## Final state (2026-10-10, end of session)

- The final integrated, reviewed tree is staged in `.claude/worktrees/p4-integ`. That worktree
  holds phase 3 (`7258f70`), phase 4 `fe25a89`, the identity fix, the integration fixes and the
  docs, as an uncommitted merge. Its snapshot is the local tag `p4-integ-snapshot-tree` (a tree object)
  (via `git write-tree`). Nothing can be committed while 1Password signing fails: probes time out
  or error.
- Integration fixes from the final review (phase 4 on phase 3):
  - The service-token mint check also requires `target.clearances ⊆ actor.clearances`.
  - A seam test: an MCP `tools/call` under a row-scoped grant is scoped and masked, and the
    audit row carries scope, masking and token_id.
  - 0005 docstring says "Revises: 0004".
  - A README sentence.
- Final gate on that tree: ruff, pyright and lint-imports are clean; pytest gives 1532 passed,
  22 skipped.
- The final review verdict is PASS WITH WARNINGS. Both IMPORTANT findings are fixed; the
  remaining items are follow-ups.
- Still to do once signing works:
  1. In `p4-mcp-auth`, commit the staged identity fix and then the docs.
  2. Rebase onto `feature/auth-row-field`, resolving to the snapshot tree.
  3. Commit the integration fixes.
  4. Commit the CLAUDE.md guardrail-4 sentence as its own commit, which needs the user's
     confirmation.
  5. Run `make check` once.

## Gate results (2026-10-10)

- `make check` (phase 4 alone plus the staged fix): green. Backend 1073 passed, 18 skipped,
  coverage 96%. Frontend 263 tests and the build pass.
- Integrated tree (phase 3 plus phase 4): ruff, pyright and lint-imports are clean, and pytest
  gives 1530 passed, 22 skipped. The PG suites (alembic, access, mcp_auth, scope) give 21 passed.
- Evals: on phase 4 alone, 15/16, with one wording flake that passed 2/2 on rerun. On the
  integrated tree, 20/20, including phase 3's goldens.
- Live smoke on the integrated tree: ALL PASS, plus the negative case `--expect-ineligible`.
  There are no raw tokens in the server log, the audit rows or `credential_events`.

## WIP commit

The WIP commit is `43aa0fe`, task 12 part A. It contains only `backend/scripts/mcp_oauth_smoke.py`, which is not yet reviewed.
- It ran end to end locally and passed every step:
  - discovery, DCR, authorize and consent;
  - token, initialize, `tools/list` and `tools/call`;
  - refresh, reuse after the grace window (family revoked), revoke, code replay;
  - a PAT.
- The negative case also passed: no `mcp:use` gives an empty `tools/list` and a 403 `no_mcp_use` at consent.
- Left to do: review the script and squash it into a proper `test(mcp): OAuth smoke script` commit.

## Next steps, in order

1. Review `43aa0fe` (the smoke script) and reword it.
2. Run the task 6 targeted tests once: `cd backend && uv run pytest tests/test_main_mcp.py tests/mcp/test_server.py tests/mcp/test_mcp_e2e.py tests/mcp/test_rate_limited_routes.py tests/mcp/test_auth_verifier.py tests/mcp/test_oauth_routes.py tests/identity/test_bearer_door.py -q`.
3. Run `make check` from the worktree root, with `frontend/node_modules/.bin` on PATH. It was started and then stopped by the pause, so there is no result yet.
4. Opt-in PG suites: DONE after integration. test_alembic_postgres 3/3, test_access_postgres 4/4, test_mcp_auth_postgres 5/5 (the code-exchange, refresh, approve, family-revoke and client-revoke races).
5. Run the evals regression: a seeded throwaway DB, `ENVIRONMENT=development`, `ANTHROPIC_API_KEY` empty, and `OPENAI_API_KEY` read from `backend/.env`. Not yet run.
6. Do the final whole-branch production review of `origin/main...HEAD`, focused on OAuth/MCP spec conformance and the security bar. Fix the findings and re-review.
7. Send the final report to the coordinator.

## Deviations and decisions

These are recorded in the plan's "As built" section and in `p4-rules.md`.
- **C8:** code reuse revokes the whole family, including the winner's tokens.
- **C5:** `access/admin.py` gets one method, one appended line and an extended identity import. There is no `import re`; the slug is built in identity.
- **C4:** `App.tsx` gets an import, a small wrapper and the route.
- **C3:** `ensure_service_user` is kept because the evals use it.
- **C7:** a missing `mcp:use` gives an empty `tools/list` and a tool-level denial over HTTP 200, not a 403.
- **C9:** `build_mcp`/`build_http_app` are factories.
- **C1:** allowed hosts for DNS rebinding come from `ATLAS_PUBLIC_URL`, and nginx sends `Host $http_host`.
- **E1:** the failed-bearer guard counts only unrecognised bearers. Private, loopback and link-local peers count as "unknown", so behind nginx or the tunnel the guard logs and never blocks. In 4a the per-source limits are global.
- **`ForbiddenError.reason` and `ExpiredTokenError`:** both are exported from identity. Consent 403s carry `detail.reason`, and the frontend switches on it.
- **Accepted:**
  - A tool call without `mcp:use` is logged with its token and client ids but writes no `atlas_audit_log` DENY row (`atlas/tools.py` hotspot). This is a follow-up.
  - A refresh token revoked by another client revokes its family.
  - `structured_output=False`. The `tools/list` JSON is byte-identical to main.
  - There is no token-scope narrowing, and revocations are written to `credential_events`.
- **Not edited:** `CLAUDE.md` guardrail 4 ("Auth/permissions come from the Firebase token") is now inaccurate for MCP. The user should add: "MCP callers use atlas-issued tokens (OAuth, PAT or service), stored only as hashes; the MCP door never honours AUTH_DISABLED."
- **Process:**
  - Commit signing failed for several hours (1Password). Tasks 4-fix, 5, 8-fix, 9, 11 and 6 were committed after it recovered, rebuilt one per task from saved patches.
  - Early on, the permission classifier denied one subagent commit (the task 4 fix). It was committed later in the normal serialized flow (`d5aaae8`).

## Last gate results

- **Task 6 fix round (full gate on the integrated tree):** ruff, format, pyright (app and evals) and lint-imports (10 contracts) were all clean. pytest -n auto: 1052 passed, 13 skipped. The frontend `pnpm -s check` was green earlier in task 6 (263 tests).
- **Task 11:** `nginx -t` passed, plus a live smoke test of the headers and log redaction. `test_deploy_config.py` passed 4 out of 4.

## Open findings

All of these are in `p4-followups.md`.
- **Precondition for 4b:** bind consent to the browser that started it, with an HttpOnly cookie.
- **Admin token list:** capped at 200 with no paging.
- **CLI:**
  - the email lookup goes through `list_users`, which does substring matching and caps at 50;
  - `create-pat` writes its structlog line to stdout, next to the token.
- **gc event:** recorded as via `"system"`.
- **uvicorn access log:** logs the `/mcp-server/authorize` query string (`state`, `code_challenge`). Neither is a secret.
- **Browser clients:** `/mcp-server/mcp` has no CORS for them, which is acceptable in 4a.

## Pending checks

- `make check` (started, then stopped by the pause)
- evals (not started)
- evals
- the final branch review
- the interactive Claude Code approval through the tunnel. The steps are in the README's MCP section; it is user-run.
