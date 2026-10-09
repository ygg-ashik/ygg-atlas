# Auth phase 5: progress checkpoint (2026-10-10)

Branch `feature/auth-admin-ui` (worktree `.claude/worktrees/p5-admin-ui`), based on origin/main ac8ba38.
Plan: `docs/plans/2026-10-09-auth-rbac-phase-5-admin-self-service.md` (decisions P5-D1..D24).
Durable inputs: `.claude/handoff/auth-p345/` (brief.md, contracts.md, phase5-analysis.md,
p5-impl-rules.md, p5-fe-rules.md, p5-review-rules.md). Approved mockup: branch
`feature/admin-ui-mockups` (e0d0f7b, e9415bd), `docs/design/reference/atlas-admin-self-service.html`.

## Done (all signed, all passed the two-stage review unless noted)

| Task | SHA | Review |
|---|---|---|
| Plan | a58d5fc | n/a |
| B1 migration 0006, AccessRequest, Page, cursor | 710e83f | approved |
| B2 staged AccessAdmin helpers | 4d21388 | approved |
| B6 catalog metadata in insights | 70400af | approved |
| F2 ui primitives + DESIGN.md | cea243a | approved (after fixes) |
| F1 api clients + hooks | 7563db1 | approved (after fixes) |
| B3 access requests | ddd6f39 | approved (after fixes) |
| F3 route guard, nav, account menu | 509955a | approved (after fixes) |
| F4 account pages + chat DeniedBlock | 9c7eb88 | approved (after fixes) |
| F5+F6 admin users, groups, grant editor | f2d3f7d | approved (after fixes) |
| B4 audit views | 2e8940a | approved (after fixes; re-review approved) |
| B5 detail, user paging, manager views (P5-D21..D24) | cc6a4e5 | approved |
| F7 requests queue | 26f856c | approved |
| F8 audit UI | dab7ef0 | approved |
| F9 tokens and connected apps | e6c7c1c | reviewed; its IMPORTANT finding fixed in 3b72850 |
| Follow-up pass (B5 wiring, F7/F8/F9/F2 fixes, plan notes) | 3b72850 | approved |

## Visual-check fixes: 4de606f (reviewed, approved)

The two unreviewed WIP commits (7ac9f0d, 0383581, written by an in-flight subagent after the
pause) were read, reviewed and folded into 4de606f `fix(admin): readable audit objects, detail
titles and toolbar crumbs`, with review fixes: an audit-only viewer never lists groups/users
(tested), deny grants read "deny <target>", and the crumb became the `ToolbarCrumb` ui primitive
(DESIGN.md `toolbar-crumb`) also used for "My access ›" on New request (per the mockup).

## Next steps, in order

1. ~~Finish + review the WIP above; frontend gate.~~ Done (4de606f).
2. `make check` at the worktree root (PATH with `frontend/node_modules/.bin`).
3. Re-run the final whole-branch review on `origin/main...HEAD` (last one: PASS WITH WARNINGS).
4. Phase-end PG tests (TEST_PG_URL, throwaway postgres:16, wrap docker in `timeout 60`).
5. B7 (structured denied block) only after phase 3 merges: backend must emit
   `{kind: "denied", resource, label}` (the frontend DeniedBlock already renders it).
6. Merge `feature/admin-ui-mockups` into the branch (`git merge --no-ff`): the attempt was refused
   by the permission classifier; needs the user's approval.

## Deviations and decisions (see plan P5-D table)

- Task split: schemas live with their task (P5-D2); `requests` and `cursor` layers only (P5-D3).
- Group requests: admin:groups decides all group kinds; admin:users role + resource (P5-D9).
- Out-of-view requests → 404 before any status check (no status leak).
- Approving for a disabled requester → 409; expired identical grant → 409 until revoked.
- Audit-log index `ix_atlas_audit_log_created_at_id` declared in `app/access/models.py` (not
  `models/audit.py`, a contracts hotspot) and created in migration 0006.
- New routes beyond the analysis: member-candidates (managers, emails shown; P5-D21), manager-scoped
  `GET /admin/groups` (P5-D22), `status=decided` (P5-D23), `user_id` filter (P5-D24).
- Frontend: no new deps; DeniedBlock uses `kind`; requesters can't browse groups (discovery via
  resource options); service-accounts page deferred (not in the mockup); "What I can see" shows a
  statement (no self-service rules endpoint).

## Last gate results (before the WIP)

- `make check` green: backend 622 passed / 13 skipped, coverage 95% (new modules 97–100%), ruff,
  pyright, lint-imports 9/9; frontend prettier, eslint, tsc, vitest 121 files / 706 tests, build.
- PG (throwaway postgres:16): 12/12 passed incl. concurrent approve (exactly one wins), cancel vs
  approve, cap under concurrent creates, partial index, UTC day bucketing; alembic up/down(0003)/up OK.
- Visual check (light/dark, reduced motion/transparency, 1440 and 1000 px): no blocking defects.

## Open findings

- IMPORTANT (integration): phase 3's `create_grant` additions (scope shape, clearance check,
  `_check_scope`, `row_scope=`) must go into `_stage_grant`, or approval-path grants skip them.
  Add a test at integration. Re-run PG tests after re-chaining 0006's down_revision to "0005".
- MINOR: permanent 409s (disabled requester, expired grant) still offer Retry in the queue UI.
- MINOR: keyset logic duplicated in `repository.list_decidable` and `admin.list_users`.
- MINOR: `insights/catalog_resources.py` imports `app.atlas.policy` directly (P5-D18); export the
  builders from `app.atlas` later.
- MINOR: groups_granting runs the evaluator per group (perf/log noise); `/account/tokens` logs 404s
  until phase 4 ships (by design); catalog preview reason for disabled targets reads "no grant".
- Visual MINORs: no tab counts (Decided, Audit), no audit range pill, 1000px name wrapping.
