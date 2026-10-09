# Auth phase 3 (Row and field): progress checkpoint

Branch `feature/auth-row-field`, worktree `.claude/worktrees/p3-row-field`, based on origin/main ac8ba38.
Plan: `docs/plans/2026-10-09-auth-rbac-phase-3-row-field.md`.
Binding inputs: `/Users/ashikbabu/Projects/ygg-atlas/.claude/handoff/auth-p345/` (brief.md, contracts.md, phase3-analysis.md).
Nothing has been pushed. No PR is open.

## Done (all signed; each reviewed in two stages, spec then quality and security)

| Task | SHA | Review |
|---|---|---|
| Plan | b450124 | n/a |
| T3 masking | dc1c6a5 | APPROVED after fixes |
| T2 scope compiler | 8e2514b | APPROVED after fixes |
| T1 registry lint and models | 495f2b5 | APPROVED after fixes. This commit also edits scope.py: shared SCOPE_TOKEN, COLUMN_PATTERN and uses_reserved_bind |
| T4 evaluator and policy | 7095787 | APPROVED |
| T5 tables, migration 0004, inputs | 7adb31e | APPROVED |
| T8 atlas enforcement | 5d08ae1 | APPROVED after fixes |
| T9 plugin YAML and seeds | b1fef5b | APPROVED |
| T6 admin writes | a25191b | APPROVED after fixes |
| T7 admin API and CLI | 5ffe6b0 | APPROVED. Minor findings left open, see below |
| T10 wiring and e2e | 66ff9b1 | APPROVED after minor fixes |

## WIP commit (unreviewed)

The WIP commit (`wip(phase3): T11, T12`, cd36f54) contains:

- **T11 evals.**
  - Finished:
    - `evals/run_evals.py`: the harness gains `attributes`, `clearances`, `{pattern, row_scope}` allows, label modes, and `expect_none`, which scans the answer, blocks and provenance.
    - `evals/goldens/row_field.yaml`: 4 goldens.
    - `backend/tests/test_eval_harness.py`: 19 offline tests, all passing.
    - Fixes 1, 2, 4 and 5 from the first review are applied.
  - Left:
    - A re-review of the delta.
    - **An open regression** (see Open findings).
- **T12 typing and docs.**
  - Finished:
    - Strict pyright on `atlas/scope.py` and `atlas/masking.py`.
    - ARCHITECTURE §2.5 (includes the D3.12 cache-key rule).
    - CLAUDE.md guardrails 2, 3 and 4: the edit was reverted to main pending the user's decision (see Resume log).
    - The README phase-3 section, with the deploy notes.
    - The spec's §5.5/§5.6 "As built" blocks.
  - Left:
    - A review.
    - The full pytest run and `make check`. Both were killed by the restart.

## Resume log (2026-10-10)

- **Eval regression root-caused.** `clarify-ambiguous-sales` is flaky on origin/main too, not a branch regression: 20 live runs each gave main 12/20 and the branch 14/20 (gpt-4.1, default temperature). The model sometimes skips ask_clarification and answers month-to-date revenue. The earlier "main 2/2, branch 0/3" was a small-sample artifact. Fix: rule 8 in `backend/app/agent/prompts.py` now says to call ask_clarification before querying any metric and not to fill in the missing period for a vague question (snapshot questions exempt); 20/20 after the fix. Test in `tests/test_prompts.py`. The golden is unchanged.
- **`out-of-registry-honesty` was also flaky on main** (4/10 on main, 5/10 on the branch): the model gave honest misses in wordings the phrase list missed. The list now has anchored honest-miss phrases, plus `expect_none: ["metric_id"]` so a proxy-metric answer fails.
- **CLAUDE.md guardrail edits from the WIP are reverted.** The user is deciding guardrail text; the proposed wording is kept in the final report.
- T11 and T12 reviewed and approved after fixes (rollback note and 0004 downgrade guard, `_DIMENSION` cap, doc accuracy).

## Status (2026-10-10, end of phase 3)

**Phase 3 is complete, reviewed and committed. Nothing has been pushed, and no PR is open.**

- **WIP folded.** The WIP commit was split into:
  - `fix(agent)` 560df04
  - `test(evals)` 051cae0
  - `fix(access)` 66b3c34 (the 0004 downgrade guard and the `_DIMENSION` cap)
  - `docs` d856461
- **Later commits:**
  - d66ece1: the PG scope test
  - a8a5fab: the placement lint
  - 218110f: error and log hygiene
  - bc5b3da: CLI docs
- **Final whole-branch review: PASS WITH WARNINGS.** Fixed: the important finding (`{{scope}}` placement lint) and minor findings 2, 4, 5 and 7. The lint was re-reviewed three times while it was being hardened; the last round was APPROVED.
- **Gates at HEAD.**
  - `make check` is green: 929 passed, 12 skipped, coverage 95.9%. Frontend: 217 passed, build OK.
  - The PG tests pass 11/11 on a throwaway "scratch" database: alembic, access and scope.
- **Live evals:** 20/20, twice at HEAD. The 6 DeepSales goldens are skipped locally.

## Open follow-ups

- **Insights:** pass `suppressed_rows` and `others_covers` through to breakdowns. The UI scope and masking chips are phase 5 / C20.
- **Duplication:** `_self_attributes` (eval harness vs repository) and `sales_rep()` (conftest vs seed).
- **Missing tests:**
  - preview tests for a disabled user's clearances and for `decision.row_scope == []`;
  - a `ProvenanceOut` test in insights.
- **Contract:** `/meta/capabilities` `label_classes` includes `category`, which PUT rejects. Tell phase 5.
- **`WHERE NOT {{scope}}`** passes the lint. It is a syntax error at runtime, so it fails closed.
- **Evals:**
  - A typed `expect_no_tool` check.
  - The agent runs at the default temperature, so prompt-sensitive goldens stay probabilistic. Re-measure them with 10+ runs before calling a regression.
- **User decisions:**
  - C10 extension and the CLI exemption.
  - CLAUDE.md guardrail text. The proposed text is in the final report.

## Deviations and decisions (beyond the plan's C1–C20)

**Scope compiler**
- Caps: 50 alternatives and 1000 binds; any overflow is denied.
- Rejects queries that use the reserved `:scope_` bind prefix. This is checked both at registry load and at compile time, with `(?<!:):scope_`.
- Rejects a bare string as a value set.
- Rejects a value list that contains duplicates.

**Evaluator**
- Treats these as malformed (deny-all): a bare-string value, an empty-string value, a non-string key, or a scope on a clearance grant.
- Treats an empty `$self` attribute as missing, so that grant is skipped.
- Clearance codes live in `access.catalog`, because of import-linter layering.

**Admin and validation**
- One shared validator, `facts.is_well_formed_scope`, is used by the schema, by `create_grant` and by the evaluator.
- Dimension keys are capped at 64 characters. The registry's `_DIMENSION` regex is still unbounded; this is a minor follow-up.
- C10 is extended. An API actor needs to hold a clearance to:
  - add a member to a group that carries a clearance allow;
  - re-parent a group so that it gains an allow or loses a deny;
  - remove a member from a group that carries a clearance deny.
- The CLI is exempt from C10. **C10 needs the user's confirmation.**
- `list_label_classes` always returns both maskable classes; a missing row is reported as suppress.
- Attribute and scope values are stripped of surrounding whitespace.
- A blank `ATLAS_PSEUDONYM_KEY` (empty or whitespace only) counts as missing.

**Atlas enforcement**
- A breakdown with no label class is suppressed.
- A malformed mask-mode object degrades to suppress.
- A denial for an entity hidden by scope is audited with the real scope reason.

**Plugins**
- `ds_revenue` uses an INNER JOIN on `corporate`. The schema has `corporate_id NOT NULL` with an FK, so this matches a LEFT JOIN. Still, run EXPLAIN and an orphan-row count on the box before deploy.

## Last gate results

- Full backend gate after T7, T10 and T11 (before T12): ruff, format, pyright, lint-imports, and `pytest -n 4`: 840 passed, 8 skipped.
- After T12: ruff, format, pyright and lint-imports pass. Pytest and `make check` have not been run.
- Live evals: 19/20.
  - `clarify-ambiguous-sales` FAILS on the branch, 3 runs out of 3.
  - It PASSES on origin/main, 2 runs out of 2.
  - The 6 DeepSales goldens are skipped locally.

## Open findings

1. **Blocking: the eval regression.** `clarify-ambiguous-sales` ("How did sales do?"). On this branch the agent answers with month-to-date revenue instead of asking a clarifying question.
2. **Minor (T7):**
   - `/meta/capabilities` `label_classes` includes `category`, which PUT rejects. It is documented by a field comment; tell phase 5.
   - There are no preview tests for a disabled user's clearances or for `decision.row_scope == []`.
   - The `cli.py` docstring example `country=AE,SA` names a dimension no plugin declares.
3. **Minor follow-ups:**
   - Cap the registry's `_DIMENSION` regex at 64 characters.
   - `sales_rep()` is duplicated between conftest and the seed script.
   - `_self_attributes` logic is duplicated between the eval harness and the repository.
   - Consider a test for `ProvenanceOut` scope and masking in `test_insights_api.py`.
4. **Deploy notes** are in the README phase-3 section:
   - set `ATLAS_PSEUDONYM_KEY`;
   - reseed the demo data;
   - set attributes with the CLI (`csm_name`, `csm_email`);
   - make scoped grants with the CLI;
   - make the first clearance grants with the CLI;
   - check `ds_revenue` with EXPLAIN;
   - deploy migration 0004 together with the code.
