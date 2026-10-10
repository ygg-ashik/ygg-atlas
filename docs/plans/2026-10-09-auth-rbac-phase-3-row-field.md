# Auth & RBAC Phase 3: Row and Field Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax
> for tracking. Before writing any code, follow `.claude/skills/engineering-standards/SKILL.md`; before
> calling a task done, run the full gate (below) and the two-stage review (spec, then
> `production-code-review`).

**Goal:** The atlas answers two more questions on every execution. **Which rows?** A grant may carry a
row scope (`{csm: [$self]}`, `{channel: [b2c]}`) that is compiled into the vetted SQL as bind
parameters. **Which labels may be shown?** Breakdown labels carry a label class (`category`,
`business_name`, `person_name`); without the matching clearance they are pseudonymised, suppressed or
bucketed, per an admin-set mode. Every gap fails closed.

**Architecture:** `app.access` evaluates row scopes (resolving `$self` from admin-set user attributes),
clearances and label-class modes into the immutable, cached `Policy`. `app.atlas` never imports
`app.access`: it asks the `ResourcePolicy` protocol for `row_scope(resource)`,
`has_clearance(code)` and `mask_mode(label_class)`, compiles `{{scope}}` with a pure compiler
(`atlas/scope.py`) and masks breakdowns with a pure masker (`atlas/masking.py`) before any result
leaves `AtlasTools`. Scope dimensions are declared per entity in plugin YAML, linted at load, and
mirrored into a `scope_dimensions` table at startup so `access` can validate grants without importing
`atlas`. Provenance and the audit log carry scope (dimension names, never values, in provenance) and
masking.

**Tech Stack:** FastAPI, SQLModel / SQLAlchemy async, Alembic, pytest (+xdist), ruff, pyright (strict for
`app/access`, and from T12 `app/atlas/scope.py` + `app/atlas/masking.py`), import-linter.

**Spec:** `docs/specs/2026-10-08-auth-rbac-design.md` §5.3, §5.5, §5.6, §6 (points 3, 4), §7, §9, §13,
§14 phase 3. Design analysis (binding): `phase3-analysis.md` D3.1–D3.14; cross-phase contracts:
`contracts.md`.

**Working directory:** worktree `/Users/ashikbabu/Projects/ygg-atlas/.claude/worktrees/p3-row-field`,
branch `feature/auth-row-field`, based on `main` @ `ac8ba38`. Backend commands run from `backend/`.

**Full gate (once per task, before its commit):**

```bash
cd backend
uv run ruff check . ../evals && uv run ruff format --check . ../evals && uv run pyright \
  && uv run pyright ../evals && uv run lint-imports && uv run pytest -n auto -q
```

Iterate with targeted tests (`uv run pytest tests/<file> -q`). `make check` once at the end (T12).

---

## Decisions this plan makes (read before starting)

From the design analysis (D3.x) and the user-approved defaults (U1–U4, `contracts.md`). Change them only
with the user. Clarifications this plan adds on top are in **Deviations / clarifications** (C1–C20).

| # | Decision | Why |
|---|---|---|
| D3.1 | `{{scope}}` compiles to `AND TRUE` (unrestricted) or `AND ((col IN (:scope_0_0, :scope_0_1)) OR ((c2 IN (:scope_1_0)) AND (c3 IN (:scope_1_1))))`. Column text comes only from YAML `scope_dimensions[d].column` (linted `^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)?$`); grant keys are dict lookups only; values are always bind params. ≤100 values per dimension per alternative. Every `{{scope}}` occurrence gets the same predicate. | No `= ANY` (Postgres-only; tests run demo on SQLite); `Connector` protocol unchanged. |
| D3.2 | Registry lint: in an entity with `scope_dimensions`, every `metrics[].query`, `metrics[].breakdown_query`, `funnels[].steps[].query` and `freshness_query` contains `{{scope}}`; any other `{{...}}` is rejected everywhere; `{{scope}}` without `scope_dimensions` is rejected; `scope_dimensions` on a non-SQL plugin (`allowed_tables is None`) is rejected; dimension `tenant` is reserved; every metric with a `breakdown_query` declares `breakdown_label_class` ∈ {category, business_name, person_name}. | Fail closed at load: no unscoped query in a scoped entity, no unlabeled breakdown. |
| D3.3 | OR across matching allows, AND within one grant. Deny wins; any matching **unscoped** allow ⇒ all rows (`None`); `()` ⇒ deny. Malformed `row_scope` (`{}`, empty list, non-string values, non-dict, bad key, >100 values, >20 dims, or a scope on a deny / non-resource grant) ⇒ the grant is malformed ⇒ deny-all for everyone it applies to (`access.malformed_grant`). D1 lifted: clearances are grantable and evaluated. | Phase-2 malformed rule; spec §15 (no row-scoped denies). |
| D3.4 | `$self` is resolved **in the evaluator**; `Policy` carries concrete values only. `PolicyInputs.attributes` = `user_attributes` rows + built-ins `email`, `user_id`. A missing attribute drops that grant's rule into `Policy.skipped` (reason `missing attribute 'csm_name'`, log `access.scope_self_unresolved`); it is NOT deny-all. See C1 for how the attribute name is found. | Per-user condition, not corruption. |
| D3.5 | `user_attributes` are admin-set only (never Firebase claims). `AccessAdmin.set_attribute` / `delete_attribute`: `admin:users`, not on yourself (409), audited `attribute.set` / `attribute.delete` with before/after, bump `policy_version`. Key `^[a-z][a-z0-9_]{0,63}$`, value 1..200 chars, one value per key. | Attributes feed scopes, so they are permissions. |
| D3.6 | Declared dimensions are mirrored into `scope_dimensions` at startup (`access.sync_scope_dimensions(db, get_registry().scope_catalog())`, wholesale replace, one transaction). Grant validation: for a pattern naming one entity, every dimension is declared by it; for wider patterns each dimension is declared by ≥1 matched entity; `$self` needs a declared `self`. Disabled plugins are not mirrored ⇒ scoped grants on them are rejected. | `access` may not import `atlas`. |
| D3.7 | In the atlas, an alternative naming a dimension the entity doesn't declare is dropped; nothing left ⇒ denied ("scope names a dimension this data does not have"), and hidden from `list_metrics` / `search_atlas` / `describe_entity`. | Discovery agrees with execution. |
| D3.8 | Masking happens once, in `AtlasTools`, via pure `atlas/masking.py`. `pseudonymise` = `"Account 7f3a1c"` / `"Person 7f3a1c"` = `HMAC-SHA256(ATLAS_PSEUDONYM_KEY, f"{label_class}:{label}")` hex[:6]; `suppress` = `rows: []` + `suppressed_rows: n`; `bucket` = first `bucket_size` rows renamed `Top 1..N`, the rest of the **fetched** rows summed into `Others` (`others_covers: "remaining fetched rows"`, U2). `category` never needs a clearance. Missing setting / unknown mode / `pseudonymise` with empty key ⇒ `suppress` (log `atlas.masking_fallback`). The clearance mapping lives in both `access/catalog.py` and `atlas/masking.py`; a test asserts they agree. | One enforcement point; agent, insights and MCP inherit it. |
| D3.9 | Label-class modes ride inside the `Policy` (`PolicyInputs.label_modes` → `Policy.label_modes`). `AccessAdmin.set_label_class`: `admin:groups`, audited `label_class.update`, bumps the version. The four `AtlasTools` construction sites (chat, insights, MCP, evals) are unchanged. | Phase 4 rewrites `mcp/server.py`. |
| D3.10 | `describe_entity` returns `fields` / `pii_fields` only when the entity resource itself (`source/entity`, i.e. a `source/entity/*`-or-wider allow) is allowed; item-only grants get `fields: {}`, `pii_fields: []`, `fields_hidden: true` and a business note. (U3) | Closes the known phase-2 leak. |
| D3.11 | `build_provenance` gains `scope={"restricted": bool, "dimensions": [names]}` (names only, never values) and `masking={"label_class", "mode"} \| None`. `atlas_audit_log` gains `scope` JSON (concrete compiled alternatives) and `masking` JSON. Prompt rule 11: a restricted answer says so briefly ("across the accounts you can see"). | Provenance on every number; audit everything. |
| D3.12 | No results cache. ARCHITECTURE records: any future result cache keys on `(user_id, policy_version, sha256(compiled scope + clearances + label modes))`. | Prevents a cross-user leak later. |
| D3.13 | Plugin annotations: demo `order` (`channel`, `sales_rep` self `rep_name`), demo `customer` (`segment`), demo `checkout` unscoped; new metric `orders_by_rep` (label class `person_name`) over a new `demo_orders.sales_rep` column; deepsales `ds_task`, `ds_account`, `ds_lead`, `ds_revenue` scoped (exact columns in T9; see C1–C3). | Real coverage on both shipped plugins; no emapi plugin exists. |
| D3.14 | `grants.row_scope` is `sa.JSON` (drift-free on both dialects). `uq_grants_subject_target` unchanged: a scoped and an unscoped allow on the same (subject, target) cannot coexist (409). | Simple, explicit. |
| U1 | `ds_revenue` gets the `csm` scope via a `corporate` join. | User default. |
| U2 | Bucket `Others` = sum of the remaining fetched rows, documented in the result. | User default. |
| U3 | `describe_entity` fields require an entity-wide allow. | User default (= D3.10). |
| U4 | `$self` has the built-in `email` attribute (and `user_id`). | User default. |
| K1 | Migration `0004_row_field.py`: `revision = "0004"`, `down_revision = "0003"  # chain: set to predecessor at integration`. | Cross-phase chain contract. |
| K2 | Columns on shared tables are **appended** at the end of the model and the migration: `grants.row_scope`; `atlas_audit_log.scope` then `atlas_audit_log.masking` (phase 4 appends `token_id`, `client_id` after them). | Clean rebase for phases 4/5. |
| K3 | API ownership: phase 3 owns, in `app/access/router.py`, exactly the routes/fields in T7's table (per-key attribute PUT/DELETE, no bulk PUT; `/meta/scope-dimensions`; new fields on `/meta/capabilities`, `/me/access`, `EffectiveAccessOut`, `GrantCreate/GrantOut`). Phase 5 binds to these shapes; do not rename. | `contracts.md`. |
| K4 | Hotspot discipline: `atlas/policy.py` — only `ResourcePolicy` additions (never `AtlasCaller`); `atlas/tools.py` `_audit` — append the two kwargs at the end; `main.py` — the sync line plus the key check (C13); `config.py` — one appended setting; README / ARCHITECTURE / CLAUDE.md / spec / `.env.example` — own sections only. | Phases 4 and 5 edit the same files. |

---

## Deviations / clarifications (resolve the analysis against the real code)

| # | Issue found | Resolution in this plan |
|---|---|---|
| C1 | **`$self` can't be resolved eagerly per grant as the analysis states**, because D3.13 gives the same dimension `csm` different `self` attributes per entity (`ds_task` → `csm_email`, `ds_account`/`ds_revenue` → `csm_name`), and a `deepsales/*` grant spans them. | Registry lint (T1): **a dimension name maps to one `self` attribute registry-wide** (all entities declaring dimension `d` declare the same `self`, or all none). `PolicyInputs` gains `self_attributes: Mapping[str, str]` (dimension → attribute), read from the `scope_dimensions` mirror (T5). `ds_task.csm` becomes `{column: assignee_name, self: csm_name}` (exactly spec §5.5's example) instead of `assignee_email`/`csm_email`, because `account_profiles` has no CSM email column. Deploy note: set `csm_name` (and `csm_email` for leads). |
| C2 | `ds_lead` declares `owner`, not `csm`. A CSM grant `deepsales/*` `--scope csm=$self` therefore hides `ds_lead` (D3.7). | Kept (fail closed; leads are sales-owned). Documented in the deploy notes: grant `deepsales/ds_lead/*` with `--scope owner=$self` separately when wanted. |
| C3 | `ds_revenue`: its two metric queries have no table alias, and the D3.2 lint also needs `{{scope}}` in the `freshness_query` and the (already-joined) breakdown. | All four `ds_revenue` queries alias `corporate_revenue_monthly m JOIN corporate c ON c.id = m.corporate_id` and carry `{{scope}}` (column `c.csm_name`). EXPLAIN on the box before deploy (risk table). |
| C4 | Analysis signature `compile_scope(query, declared: Mapping[str, ScopeDimensionDef], scope)` makes T2 depend on T1's model (same parallel group). | `compile_scope(query: str, columns: Mapping[str, str], scope: RowScope \| None)` — dimension → column text. `AtlasTools` passes `{d: v.column for d, v in entity.scope_dimensions.items()}`. |
| C5 | `MaskMode` in `atlas/policy.py` (T8) is needed by T3 (group 1), and `access.Policy.mask_mode` cannot return an atlas type. | `atlas/masking.py` (T3) defines `MaskMode` as a **Protocol** (read-only `mode: str`, `bucket_size: int`); `atlas/policy.py` imports it. `access.policy.LabelMode` (frozen dataclass, T4) satisfies it structurally. |
| C6 | Analysis has `Rule.scope: tuple[Mapping...] \| None`, but one grant is one conjunction; and Mappings make `Rule` unhashable. | `Rule.scope: tuple[tuple[str, frozenset[str]], ...] \| None` — one conjunction, sorted `(dimension, values)` pairs, hashable. `Policy.row_scope()` returns `tuple[dict[str, frozenset[str]], ...]`. API shape: `allow[].row_scope: dict[str, list[str]] \| None`. |
| C7 | T1's new `breakdown_label_class` lint would fail `test_every_shipped_definition_passes_the_lint` until T9 (group 2). | **T1** adds `breakdown_label_class` to the 8 existing breakdowns in the shipped YAML (demo `orders.yaml`; deepsales `accounts`, `leads`, `revenue`, `tasks`). T9 adds scope dimensions, `{{scope}}` and `orders_by_rep`. |
| C8 | Analysis puts `sync_scope_dimensions` after `prepare_access`; the mirror feeds evaluation (C1), so a change must be followed by a version bump, and `test_apply_startup_increments_the_policy_version` asserts exactly +1. | `apply_startup` calls `sync_scope_dimensions` **before** `prepare_access`; sync never bumps; `prepare_access`'s unconditional bump invalidates any policy cached against the old mirror. |
| C9 | Several scoped queries have no `WHERE` (e.g. demo `freshness_query`, `customers_total`), and `{{scope}}` expands to `AND …`. | Authors write `WHERE TRUE {{scope}}`; `{{scope}}` always sits before `GROUP BY` / `ORDER BY` / `LIMIT`. T9 executes every scoped demo query on SQLite to prove it. |
| C10 | Analysis is silent on self-escalation for clearance grants. | D10 analogue: an API actor may **grant a clearance allow, or revoke a clearance deny, only if they hold that clearance** (`actor.policy.has_clearance`); the CLI (D5) is exempt. Admins get their first clearance via the CLI (deploy notes). **Confirm with the user** in the PR description. |
| C11 | Built-ins `email` / `user_id` share the attribute namespace. | `set_attribute` rejects reserved keys `email`, `user_id` (422); built-ins override stored rows in `attributes_for`. |
| C12 | `PUT /admin/label-classes/category` is meaningless (`category` is never masked). | Only `business_name`, `person_name` are settable (422 otherwise); `GET` lists those two. `bucket_size` 1..50 (= `MAX_BREAKDOWN_LIMIT`). |
| C13 | `AtlasTools` construction sites must stay unchanged (D3.9) yet masking needs the key. | `AtlasTools.__init__` gains keyword-only `pseudonym_key: str \| None = None`; `None` ⇒ `get_settings().atlas_pseudonym_key` read lazily at mask time (`app.atlas` → `app.config` is allowed by the contracts; `lint-imports` verifies). Production with an empty key: `apply_startup` logs `atlas.pseudonym_key_missing` at error level (two lines in `main.py`, next to the sync line). |
| C14 | Analysis rule 11 covers `restricted` only; masked answers risk invented names. | Rule 11 also says: when a breakdown's labels are masked or suppressed, never guess names; say names are hidden by access settings. |
| C15 | `_audit` is called once per `execute()` and must learn the scope/masking of that call. | A `ContextVar[_CallTrace \| None]` set in `execute()`; helpers record into it; `_audit` reads it. Safe if a caller ever runs tools concurrently. |
| C16 | Shapes not pinned by the analysis. | Provenance `scope` is present on every metric/funnel provenance (`{"restricted": false, "dimensions": []}` for unscoped data). Audit `scope`: `None` when no query ran; `{"restricted": false}`; or `{"restricted": true, "alternatives": [{"channel": ["b2c"]}]}`. Audit `masking`: `None` or `{"label_class", "mode", "rows_in", "rows_out"}`. |
| C17 | `tests/conftest.py` uses `create_all` (no migration seeds), and conftest is T9's file in group 2. | Conftest does **not** seed `label_class_settings`; a missing row ⇒ `suppress` (fail closed). Tests that need modes call `access_helpers.seed_label_classes(db)` (T5). |
| C18 | A pydantic field literally named `self` is awkward. | `ScopeDimensionDef.self_attribute: str \| None = Field(default=None, alias="self")`, `populate_by_name=True`; YAML keeps `self:`. |
| C19 | "Policy satisfies ResourcePolicy" (T4 in the analysis) can't be checked before T8 extends the protocol; same for the clearance-mapping cross-check (needs T3 + T4). | Both tests live in T8 (`tests/test_atlas_access.py`). |
| C20 | Frontend. | No frontend change: provenance keys are additive; `describe_entity` output is not rendered. |

---

## File map

| File | Task | Change |
|---|---|---|
| `backend/app/atlas/models.py` | T1 | `ScopeDimensionDef`; `EntityDef.scope_dimensions`; `MetricDef.breakdown_label_class` |
| `backend/app/atlas/registry.py` | T1 | D3.2 + C1 lints; `scope_catalog()` |
| `backend/app/sources/demo/definitions/orders.yaml` | T1, T9 | T1: label class; T9: dimensions, `{{scope}}`, `orders_by_rep` |
| `backend/app/sources/demo/definitions/customers.yaml` | T9 | `segment` dimension, `{{scope}}` |
| `backend/app/sources/deepsales/definitions/{accounts,leads,revenue,tasks}.yaml` | T1, T9 | T1: label classes; T9: dimensions, `{{scope}}`, `ds_revenue` join |
| `backend/app/atlas/scope.py` (new) | T2 | Pure compiler: `RowScope`, `CompiledScope`, `narrow_scope`, `compile_scope` |
| `backend/app/atlas/masking.py` (new) | T3 | Pure masker: `MaskMode` protocol, `CLEARANCE_FOR_CLASS`, `mask_breakdown` |
| `backend/app/access/facts.py` | T4 | `GrantFacts.row_scope`; `PolicyInputs.attributes / self_attributes / label_modes`; vocab constants |
| `backend/app/access/catalog.py` | T4 | `CLEARANCES` |
| `backend/app/access/policy.py` | T4 | `Rule.scope`, `SkippedRule`, `LabelMode`, `Policy.clearances / label_modes / skipped`, `row_scope`, `has_clearance`, `mask_mode` |
| `backend/app/access/evaluator.py` | T4 | Scope validation + `$self`, clearances, label modes; D1 lifted |
| `backend/app/access/models.py` | T5 | `UserAttribute`, `LabelClassSetting`, `ScopeDimension`; `Grant.row_scope` (appended) |
| `backend/app/models/audit.py` | T5 | `scope`, `masking` JSON (appended) |
| `backend/migrations/versions/0004_row_field.py` (new) | T5 | Tables, seed, appended columns |
| `backend/app/access/repository.py` | T5, T6 | T5: evaluator reads; T6: admin reads/writes, mirror sync |
| `backend/app/access/service.py` | T5, T7 | T5: `_inputs`; T7: `describe` gains clearances |
| `backend/app/atlas/policy.py` | T8 | `ResourcePolicy` additions; re-export `RowScope`, `MaskMode` |
| `backend/app/atlas/tools.py` | T8 | Scope + masking enforcement, `describe_entity`, provenance, trace, `_audit` |
| `backend/app/atlas/provenance.py` | T8 | `scope`, `masking` kwargs |
| `backend/app/atlas/__init__.py` | T8 | Export `RowScope`, `MaskMode` |
| `backend/scripts/seed_demo.py` | T9 | `sales_rep` column + deterministic values |
| `backend/app/access/admin.py` | T6 | Scope validation in `create_grant`, clearance grants, attributes, label classes, scope-dimension listing |
| `backend/app/access/startup.py` | T6 | `sync_scope_dimensions` |
| `backend/app/access/schemas.py` | T6, T7 | T6: `GrantCreate/GrantOut.row_scope`, `AttributePut`, `LabelClassPut`; T7: response models, catalog/effective-access fields |
| `backend/app/access/__init__.py` | T6 | Export `sync_scope_dimensions` |
| `backend/app/access/router.py` | T7 | New routes |
| `backend/app/access/cli.py` | T7 | `--scope`, `--kind clearance`, attribute / label-class / scope-dimension commands |
| `backend/app/main.py` | T10 | Sync line + key check (C8, C13) |
| `backend/app/config.py` | T10 | `atlas_pseudonym_key` (appended) |
| `backend/app/agent/prompts.py` | T10 | Rule 11 |
| `backend/app/insights/schemas.py` | T10 | `ProvenanceOut.scope / masking` (optional) |
| `backend/.env.example` | T10 | `ATLAS_PSEUDONYM_KEY` |
| `evals/run_evals.py`, `evals/goldens/row_field.yaml` (new) | T11 | Scoped/cleared policies, `expect_none`, 4 goldens |
| `backend/pyproject.toml`, `ARCHITECTURE.md`, `CLAUDE.md`, `README.md`, spec | T12 | Strict typing, docs, deploy notes |
| Tests | each task | Listed per task; new files preferred over editing shared ones |

---

## Parallel groups and file overlaps

Order: **G1 {T1, T2, T3, T4} → G2 {T5, T8, T9} → G3 {T6} → G4 {T7, T10} → G5 {T11, T12}.**
Shared fixtures have one owner each: `tests/fakes.py` T8; `tests/conftest.py` T9;
`tests/access_helpers.py` T5; `app/atlas/__init__.py` T8; `app/access/__init__.py` T6.

| Group | Files per task | Overlap | Verdict |
|---|---|---|---|
| G1 | T1: atlas `models.py`, `registry.py`, `tests/test_registry.py`, 5 YAML files (label classes only). T2: `atlas/scope.py`, `tests/test_scope_compiler.py`. T3: `atlas/masking.py`, `tests/test_masking.py`. T4: access `facts.py`, `catalog.py`, `policy.py`, `evaluator.py`, `tests/access/test_evaluator.py` (one test removed), `tests/access/test_evaluator_row_field.py`, `tests/access/test_catalog.py`. | None. C4/C5 remove the T1→T2 and T8→T3 type dependencies. | **Fully parallel.** Commit in any order. |
| G2 | T5: access `models.py`, `repository.py`, `service.py`, `models/audit.py`, migration 0004, `tests/test_alembic.py`, `tests/test_alembic_postgres.py` (if it lists tables), `tests/access_helpers.py`, `tests/access/test_row_field_inputs.py`. T8: atlas `policy.py`, `tools.py`, `provenance.py`, `__init__.py`, `tests/fakes.py`, `tests/test_atlas_access.py`, `tests/test_atlas_scope.py`, `tests/test_atlas_masking.py`. T9: YAML (demo + deepsales), `scripts/seed_demo.py`, `tests/conftest.py`, `tests/test_deepsales_plugin.py`, `tests/test_demo_scoped_definitions.py`. | **No shared files, but two hard ordering dependencies:** T8's `_audit` writes `AtlasAuditLog.scope/masking` (T5's columns); T9's `{{scope}}` YAML only executes once T8's `AtlasTools` compiles it (before that, every demo test breaks on a literal `{{scope}}`). | **Develop all three concurrently; commit T5 → T8 → T9.** T8 rebases onto T5's commit before its gate; T9 onto T8's. T9's conftest/seed edits are harmless earlier but ship in T9's single commit. |
| G3 | T6: access `admin.py`, `startup.py`, `schemas.py`, `repository.py`, `__init__.py`, `tests/access/test_admin_grants.py` (one case), new `tests/access/test_admin_{scopes,attributes,label_classes}.py`, `tests/access/test_scope_dimension_sync.py`. | — | Alone. Needs T4 + T5. |
| G4 | T7: access `router.py`, `schemas.py`, `service.py` (`describe`), `cli.py`, new `tests/access/test_row_field_api.py`, `tests/access/test_cli_row_field.py`. T10: `main.py`, `config.py`, `agent/prompts.py`, `insights/schemas.py`, `backend/.env.example`, `tests/test_prompts.py`, `tests/test_startup.py`, `tests/test_config.py`, new `tests/test_row_field_e2e.py`. | None (T10 imports `sync_scope_dimensions` already exported by T6; T10's e2e uses `AccessAdmin`, not the routes). | **Fully parallel.** |
| G5 | T11: `evals/run_evals.py`, `evals/goldens/row_field.yaml`. T12: `pyproject.toml`, `ARCHITECTURE.md`, `CLAUDE.md`, `README.md`, spec. | None (T11 must not edit README). | **Fully parallel.** T12 runs `make check` last, after T11 commits. |

---

### Task 1: Atlas models and registry lint

**Files:** modify `backend/app/atlas/models.py`, `backend/app/atlas/registry.py`,
`backend/tests/test_registry.py`; add `breakdown_label_class` to the shipped YAML (C7).

- [ ] **Step 1: failing tests** in `tests/test_registry.py`, using the existing `tmp_path` plugin pattern
  (`SourcePlugin(id=..., definitions_dir=tmp_path, allowed_tables={...})`):
  - `test_scoped_entity_queries_must_contain_scope` — parametrized over metric query, breakdown,
    funnel step, freshness: each missing `{{scope}}` ⇒ `ValueError` naming the query and file.
  - `test_unknown_template_placeholders_are_rejected` — `{{tenant}}`, `{{ scope }}` ⇒ error, also in
    an unscoped entity.
  - `test_scope_placeholder_without_dimensions_is_rejected`.
  - `test_scope_dimensions_on_a_non_sql_plugin_are_rejected` (`allowed_tables=None`).
  - `test_tenant_is_a_reserved_dimension`.
  - `test_dimension_names_and_columns_are_linted` — `Bad`, `a-b`, column `x; drop`, `a.b.c` rejected;
    `c.csm_name`, `assignee_name` accepted.
  - `test_self_attribute_is_linted` (`^[a-z][a-z0-9_]{0,63}$`).
  - `test_a_dimension_has_one_self_attribute_across_the_registry` (C1) — two entities, same dimension,
    different `self` ⇒ error; same `self` ⇒ OK.
  - `test_breakdowns_need_a_label_class` and `test_label_class_must_be_known`.
  - `test_scope_catalog_lists_every_declared_dimension` — returns
    `[("demo", "order", "channel", None, "..."), ...]`, sorted.
  - Existing `test_every_shipped_definition_passes_the_lint` must stay green (C7).
- [ ] **Step 2: implement.**
  - `models.py`:

    ```python
    class ScopeDimensionDef(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        column: str
        self_attribute: str | None = Field(default=None, alias="self")
        description: str = ""
    # MetricDef:  breakdown_label_class: str | None = None
    # EntityDef:  scope_dimensions: dict[str, ScopeDimensionDef] = Field(default_factory=dict)
    ```

  - `registry.py`: module constants `SCOPE_TOKEN = "{{scope}}"`, `LABEL_CLASSES = ("category",
    "business_name", "person_name")`, regexes `_DIMENSION = ^[a-z][a-z0-9_]*$`, `_COLUMN`, `_ATTRIBUTE`,
    `_PLACEHOLDER = re.compile(r"\{\{.*?\}\}")`, `RESERVED_DIMENSIONS = {"tenant"}`. New
    `_lint_scope(plugin, entity, where)` called from `_load_definition_file` after the existing table
    lints; it walks a `_queries(entity)` generator yielding `(what, sql)` for every query (reuse it for
    the placeholder check). Label-class check goes in `_register_metric` next to the `:limit` check.
    The C1 cross-entity check runs once in `__init__` after all plugins load (`_lint_self_attributes`).
    `scope_catalog()` returns sorted tuples `(source, entity, dimension, self_attribute, description)`.
  - YAML (C7): `breakdown_label_class: category` on demo `revenue`, `ds_total_accounts`,
    `ds_leads_created`; `business_name` on `ds_at_risk_accounts`, `ds_portfolio_revenue_ytd`,
    `ds_revenue_aed`; `person_name` on `ds_open_tasks`, `ds_overdue_tasks`.
- [ ] **Step 3:** `uv run pytest tests/test_registry.py tests/test_deepsales_plugin.py -q`, then the full gate.
- [ ] **Acceptance:** every D3.2 rule and C1 has a failing-then-passing test; shipped definitions load;
  commit `feat(atlas): scope dimensions and label classes in the registry`.

### Task 2: Scope compiler (pure)

**Files:** create `backend/app/atlas/scope.py`, `backend/tests/test_scope_compiler.py`.

- [ ] **Step 1: failing tests** (pure unit tests plus one SQLite run against the `db` fixture's demo rows):
  - `test_unrestricted_compiles_to_and_true` — `scope=None` ⇒ `sql` has `AND TRUE`, `params == {}`,
    `restricted is False`.
  - `test_one_alternative` — `({"channel": frozenset({"b2c"})},)` ⇒
    `AND ((channel IN (:scope_0_0)))`, `params == {"scope_0_0": "b2c"}`.
  - `test_two_alternatives_are_ored` and `test_dimensions_in_one_alternative_are_anded` (exact SQL;
    dimensions and values sorted, so output is deterministic).
  - `test_every_placeholder_gets_the_same_predicate` — two `{{scope}}` ⇒ both replaced, same bind names.
  - `test_undeclared_dimensions_are_dropped` — alternative `{csm, channel}` against `{"channel": ...}`
    columns is dropped whole; `narrow_scope` returns the rest.
  - `test_dropping_everything_raises` and `test_empty_scope_raises` (`ScopeCompileError`).
  - `test_too_many_values_raises` (>100).
  - `test_query_without_placeholder_and_a_scope_raises` (fail closed; lint should prevent it).
  - `test_adversarial_values_only_ever_reach_params` — parametrized `"' OR 1=1 --"`, `"); DROP TABLE x"`,
    `"ü"`, `":limit"`, `"{{scope}}"`: value ∉ `sql`, value ∈ `params.values()`, and
    `app.sources.base.assert_read_only(sql)` passes.
  - `test_compiled_sql_runs_on_sqlite(db)` — compile the demo revenue query with
    `channel IN (b2c)` and execute via `get_connector("demo").fetch_one` over the last 7 full days ⇒
    `3500`; unrestricted ⇒ `10500`.
- [ ] **Step 2: implement** (strict-typing clean; T12 adds it to the strict list):

  ```python
  type ScopeAlternative = Mapping[str, frozenset[str]]   # dimension -> values, ANDed
  type RowScope = tuple[ScopeAlternative, ...]           # ORed; () never means all rows
  SCOPE_TOKEN: Final = "{{scope}}"; MAX_SCOPE_VALUES: Final = 100
  UNDECLARED: Final = "scope names a dimension this data does not have"

  class ScopeCompileError(ValueError): ...

  @dataclass(frozen=True, slots=True)
  class CompiledScope:
      sql: str; params: dict[str, str]; restricted: bool
      dimensions: tuple[str, ...]; alternatives: RowScope

  def narrow_scope(scope: RowScope | None, columns: Mapping[str, str]) -> RowScope | None
  def compile_scope(query: str, columns: Mapping[str, str], scope: RowScope | None) -> CompiledScope
  ```

  `narrow_scope` drops alternatives naming an undeclared dimension, returns `None` unchanged, raises
  `ScopeCompileError(UNDECLARED)` when a non-empty scope narrows to `()`, and raises on `()` input.
  Bind names `scope_{i}_{j}` (`i` alternative, `j` running per alternative). No f-string ever
  interpolates a value; column text comes only from `columns`.
- [ ] **Step 3:** targeted tests, full gate. **Acceptance:** all above green; commit
  `feat(atlas): compile row scopes into bound predicates`.

### Task 3: Masking (pure)

**Files:** create `backend/app/atlas/masking.py`, `backend/tests/test_masking.py`.

- [ ] **Step 1: failing tests:**
  - `test_category_is_never_masked` and `test_cleared_rows_are_untouched` (`cleared=True`).
  - `test_pseudonymise_is_stable_and_keyed` — same label ⇒ same `"Person xxxxxx"`; different key ⇒
    different; `business_name` ⇒ `"Account …"`; same label in two classes ⇒ different tokens; values kept.
  - `test_pseudonymise_without_a_key_suppresses` (logs `atlas.masking_fallback`, use `structlog.testing.capture_logs`).
  - `test_suppress_drops_rows_and_counts_them` ⇒ `rows == []`, `suppressed_rows == 3`.
  - `test_bucket_ranks_and_sums_the_rest` — 5 rows, size 2 ⇒ `Top 1`, `Top 2`, `Others` (sum of
    rows 3..5), `others_covers == "remaining fetched rows"`.
  - `test_bucket_with_fewer_rows_than_the_size` ⇒ no `Others` row.
  - `test_unknown_mode_or_missing_setting_suppresses` (`mode=None`, `mode.mode == "shred"`).
- [ ] **Step 2: implement:**

  ```python
  class MaskMode(Protocol):
      @property
      def mode(self) -> str: ...
      @property
      def bucket_size(self) -> int: ...

  CATEGORY: Final = "category"
  CLEARANCE_FOR_CLASS: Final[Mapping[str, str]] = MappingProxyType(
      {"business_name": "fields:business_names", "person_name": "fields:people_names"})
  _PREFIX = {"business_name": "Account", "person_name": "Person"}
  OTHERS_COVERS: Final = "remaining fetched rows"

  @dataclass(frozen=True, slots=True)
  class MaskedBreakdown:
      rows: list[dict[str, Any]]; applied: str | None   # effective mode, None = untouched
      suppressed_rows: int | None = None; others_covers: str | None = None

  def mask_breakdown(rows: Sequence[Mapping[str, Any]], label_class: str, *, cleared: bool,
                     mode: MaskMode | None, key: str) -> MaskedBreakdown
  ```

  `hmac.new(key.encode(), f"{label_class}:{label}".encode(), hashlib.sha256).hexdigest()[:6]`.
  An unknown `label_class` is treated as maskable with `suppress` (fail closed).
- [ ] **Step 3:** targeted tests, full gate. **Acceptance:** commit `feat(atlas): mask breakdown labels by class`.

### Task 4: Evaluator, Policy, facts, catalog

**Files:** modify `backend/app/access/{facts,catalog,policy,evaluator}.py`,
`backend/tests/access/test_evaluator.py` (delete `test_clearance_grants_are_ignored_until_phase_3`),
`backend/tests/access/test_catalog.py`; create `backend/tests/access/test_evaluator_row_field.py`
(own local `grant()` / `policy()` helpers; do not import from another test module).

- [ ] **Step 1: failing tests** (table-driven where natural):
  - `test_an_unscoped_allow_wins` — scoped + unscoped allows matching ⇒ `row_scope(r) is None`.
  - `test_two_scoped_grants_are_ored` ⇒ two alternatives; `test_one_grant_ands_its_dimensions`.
  - `test_only_matching_allows_contribute` — scoped `demo/order/*` and scoped `deepsales/*` ⇒ only one
    alternative for `demo/order/revenue`.
  - `test_deny_beats_a_scoped_allow` ⇒ `allows` False and `row_scope == ()`.
  - `test_self_resolves_from_an_attribute` — `self_attributes={"csm": "csm_name"}`,
    `attributes={"csm_name": "Rania"}` ⇒ `{"csm": {"Rania"}}`; mixed `["$self", "Omar"]` ⇒ both.
  - `test_self_resolves_from_the_email_builtin` (U4).
  - `test_a_missing_attribute_skips_the_grant` ⇒ no allow rule, `skipped[0].reason ==
    "missing attribute 'csm_name'"`, other grants unaffected, not deny-all; log `access.scope_self_unresolved`.
  - `test_self_on_a_dimension_without_a_self_attribute_skips` (reason `dimension 'x' has no $self attribute`).
  - `test_malformed_row_scope_denies_everything` — parametrized `{}`, `{"csm": []}`, `{"csm": [1]}`,
    `["csm"]`, `{"Bad": ["x"]}`, 101 values, 21 dims, a scope on a deny, a scope on a capability ⇒
    `allows("*"-covered)` False, `capabilities == frozenset()`.
  - `test_clearances_are_allows_minus_denies` (group + user grants; unknown clearance codes ignored;
    inactive policy ⇒ `has_clearance` False).
  - `test_label_modes_ride_in_the_policy` and `test_mask_mode_unknown_class_is_none`.
  - `test_catalog.py`: `test_clearances_are_described` (`CLEARANCES` keys ==
    `{"fields:business_names", "fields:people_names"}`).
- [ ] **Step 2: implement.**
  - `facts.py`: remove the "ignored until then" comment on `KIND_CLEARANCE`; add
    `CLEARANCE_BUSINESS_NAMES`, `CLEARANCE_PEOPLE_NAMES`, `LABEL_CLASSES`, `MASKABLE_LABEL_CLASSES =
    ("business_name", "person_name")`, `MASK_MODES = ("pseudonymise", "suppress", "bucket")`,
    `SELF_TOKEN = "$self"`, `BUILTIN_ATTRIBUTES = ("email", "user_id")`, `MAX_SCOPE_DIMENSIONS = 20`,
    `MAX_SCOPE_VALUES = 100`, `MAX_ATTRIBUTE_VALUE = 200`, `SCOPE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")`.
    Append defaulted fields: `GrantFacts.row_scope: Mapping[str, Sequence[str]] | None = None`;
    `PolicyInputs.attributes`, `self_attributes: Mapping[str, str]`, `label_modes: Mapping[str,
    tuple[str, int]]` (all `field(default_factory=dict)`), so every existing constructor keeps working.
  - `catalog.py`: `CLEARANCES: Final[Mapping[str, str]]` (descriptions in business language).
  - `policy.py`: `Rule.scope` (C6); `SkippedRule(pattern, grant_id, origin, reason)`;
    `LabelMode(mode: str, bucket_size: int = 5)`; `Policy` gains `clearances`, `label_modes:
    Mapping[str, LabelMode]`, `skipped`. Methods:

    ```python
    def row_scope(self, resource: str) -> tuple[dict[str, frozenset[str]], ...] | None:
        if not self.decide(resource).allowed: return ()
        matching = [r for r in self.allow_rules if matches(r.pattern, resource)]
        if any(r.scope is None for r in matching): return None
        return tuple(dict.fromkeys(dict(r.scope) ... ))   # dedupe identical conjunctions
    def has_clearance(self, clearance: str) -> bool: return self.active and clearance in self.clearances
    def mask_mode(self, label_class: str) -> LabelMode | None: return self.label_modes.get(label_class)
    ```

  - `evaluator.py`: extend `_is_malformed` with `_malformed_scope(g)` (D3.3 list). In
    `_resource_rules` stop skipping clearances (they go to `_clearances`); for a valid allow with a
    scope, `_resolve_scope(g, inputs)` returns the hashable conjunction or a skip reason. Return
    `allow, deny, skipped`. New `_clearances(grants)` = allow targets ∈ `CLEARANCES` minus deny targets,
    empty if any grant is malformed (same as `_capabilities`). `label_modes` = `{c: LabelMode(m, n)}`
    for `c ∈ MASKABLE_LABEL_CLASSES` and `m ∈ MASK_MODES` (anything else is left out ⇒ atlas suppresses).
- [ ] **Step 3:** `uv run pytest tests/access -q`, full gate. **Acceptance:** commit
  `feat(access): evaluate row scopes, clearances and label modes`.

### Task 5: Tables, migration 0004, repository and service inputs

**Files:** modify `backend/app/access/models.py`, `backend/app/models/audit.py`,
`backend/app/access/repository.py`, `backend/app/access/service.py`, `backend/tests/test_alembic.py`,
`backend/tests/test_alembic_postgres.py` (only if it enumerates tables), `backend/tests/access_helpers.py`;
create `backend/migrations/versions/0004_row_field.py`, `backend/tests/access/test_row_field_inputs.py`.

- [ ] **Step 1: failing tests:**
  - `test_alembic.py`: `test_row_field_tables_and_seeds` — at head: tables `user_attributes`,
    `label_class_settings`, `scope_dimensions`; seeds `person_name=suppress`, `business_name=pseudonymise`,
    `bucket_size=5`; `grants.row_scope` and `atlas_audit_log.scope/masking` exist and are the **last**
    columns (K2). `test_row_field_downgrade_round_trips` — `downgrade("0003")` drops them,
    `upgrade("head")` restores. `test_bad_label_mode_is_rejected` (CHECK). Existing
    `test_head_matches_model_columns` covers drift.
  - `test_row_field_inputs.py`: `test_grants_for_returns_row_scope`;
    `test_attributes_include_the_builtins` (email, `user_id`; built-ins win over a stored `email` row);
    `test_label_modes_are_read`; `test_self_attributes_come_from_the_mirror` (a dimension with two
    different `self` values in the mirror is left out, logged — fail closed);
    `test_an_attribute_change_reaches_the_next_policy` (helper write + bump ⇒ `policy_for` sees it).
- [ ] **Step 2: implement.**
  - `access/models.py` (TIMESTAMP(timezone=True) everywhere):
    `UserAttribute` (`user_attributes`; PK `user_id` FK users + `key` varchar 64; `value` varchar 200;
    `set_by` FK users NULL; `set_at`). `LabelClassSetting` (`label_class_settings`; PK `label_class`
    varchar 32; `mode` varchar 16, `CheckConstraint("mode IN ('pseudonymise', 'suppress', 'bucket')",
    name="ck_label_class_settings_mode")`; `bucket_size` int default 5, server_default `"5"`,
    `CheckConstraint("bucket_size > 0", name="ck_label_class_settings_bucket_size")`; `updated_at`).
    `ScopeDimension` (`scope_dimensions`; PK `source`, `entity`, `dimension` varchar 64;
    `self_attribute` varchar 64 NULL; `description` varchar 200 default `""`; `synced_at`).
    `Grant.row_scope: dict[str, list[str]] | None = Field(default=None, sa_column=Column(JSON))` —
    **last field**. Update the module docstring (row scopes no longer "arrive in phase 3").
  - `models/audit.py`: append `scope` and `masking` (`dict | None`, `sa_column=Column(JSON)`) after
    `created_at`.
  - Migration `0004_row_field.py` (style of 0003; `batch_alter_table` for SQLite):

    ```python
    revision = "0004"
    down_revision = "0003"  # chain: set to predecessor at integration
    ```

    `upgrade`: create the three tables, seed two label-class rows, `add_column` `grants.row_scope`,
    then `atlas_audit_log.scope`, then `atlas_audit_log.masking`. `downgrade`: reverse order. Docstring:
    deploy only with the phase-3 code (D3.3 deploy consequence; the container runs `alembic upgrade head`).
  - `repository.py`: `_grant_facts` passes `row_scope`; new reads `attributes_for(user_id) -> dict[str,
    str]` (rows, then built-ins `email` = `users.email`, `user_id` = `str(id)`), `label_modes() ->
    dict[str, tuple[str, int]]`, `self_attributes() -> dict[str, str]` (C1). All with
    `populate_existing=True` like the existing reads.
  - `service.py` `_inputs`: pass `attributes`, `self_attributes`, `label_modes`.
  - `access_helpers.py`: `add_grant(..., row_scope=None)`; new `set_attribute(db, user, key, value)`,
    `seed_label_classes(db, person="suppress", business="pseudonymise", bucket=5)`,
    `mirror_dimensions(db, rows)`; each bumps the version (C17).
- [ ] **Step 3:** `uv run pytest tests/test_alembic.py tests/access -q`; with `TEST_PG_URL` set also
  `tests/test_alembic_postgres.py` (drift + CHECK names). Full gate. **Acceptance:** commit
  `feat(access): row-scope, attribute, label-class and scope-dimension tables`. **Commit before T8.**

### Task 8: Atlas enforcement (scope, masking, describe, provenance, audit)

**Files:** modify `backend/app/atlas/{policy,tools,provenance,__init__}.py`, `backend/tests/fakes.py`,
`backend/tests/test_atlas_access.py`; create `backend/tests/test_atlas_scope.py`,
`backend/tests/test_atlas_masking.py`. Needs T1–T5 (rebase on T5 before the gate).

- [ ] **Step 1: test doubles.** `fakes.StaticPolicy` gains `row_scopes: Sequence[tuple[str, RowScope |
  None]] = ()` (first matching pattern wins; none ⇒ `None`), `clearances: frozenset[str] | None = None`
  (`None` = cleared for everything, so existing breakdown tests stay unmasked), `modes: Mapping[str,
  tuple[str, int]] = {}`; methods `row_scope`, `has_clearance`, `mask_mode` (returns a small frozen
  dataclass). `make_tools` passes them through plus `pseudonym_key="test-key"`. Extend `ExplodingPolicy`
  and `VerboseDenyPolicy` in `test_atlas_access.py` with the three methods (pyright).
- [ ] **Step 2: failing tests.** Scope tests use an ad-hoc registry over the real demo tables
  (`AtlasRegistry(plugins={"demo": SourcePlugin(id="demo", definitions_dir=tmp_path, ...)})` with a
  scoped copy of the order YAML: `channel` dimension), so T8 does not depend on T9. A recording
  connector monkeypatched over `app.atlas.tools.get_connector` captures `(sql, params)`.
  - `test_every_query_kind_is_compiled` — `query_metric`, `metric_breakdown`, each funnel step and the
    freshness query: no `{{scope}}` left, `scope_0_0` bound, `start`/`end`/`limit` intact.
  - `test_scoped_revenue_is_3500_and_unscoped_10500` (real SQLite, last 7 full days).
  - `test_compare_periods_scopes_both_periods`.
  - `test_an_undeclared_dimension_is_hidden_denied_and_audited` — `list_metrics` omits it,
    `search_atlas` omits it, `query_metric` ⇒ error, audit row `decision="deny"`,
    `deny_reason == UNDECLARED`.
  - `test_an_empty_row_scope_denies` and `test_a_failing_row_scope_denies` (exception ⇒ fail closed,
    `POLICY_FAILED`).
  - `test_describe_entity_hides_fields_on_an_item_grant` (`fields == {}`, `pii_fields == []`,
    `fields_hidden is True`); `test_describe_entity_shows_fields_on_an_entity_grant` (`demo/order/*`).
  - `test_provenance_names_dimensions_not_values` — `{"restricted": True, "dimensions": ["channel"]}`,
    `"b2c"` nowhere in the provenance; unscoped ⇒ `{"restricted": False, "dimensions": []}`.
  - `test_audit_records_scope_and_masking` — row `scope == {"restricted": True, "alternatives":
    [{"channel": ["b2c"]}]}`; list_metrics row `scope is None` (C16).
  - `test_atlas_masking.py`: per mode against a fake breakdown (`person_name`): uncleared + suppress ⇒
    `rows == []`, `suppressed_rows`; pseudonymise ⇒ `"Person …"` and provenance `masking ==
    {"label_class": "person_name", "mode": "pseudonymise"}`; bucket; cleared ⇒ untouched,
    `masking is None`; `category` ⇒ untouched; missing mode ⇒ suppress; empty key ⇒ suppress;
    `has_clearance` raising ⇒ suppress.
  - `test_atlas_access.py`: extend `test_the_real_access_policy_satisfies_the_atlas_contract` with a
    real `evaluate()` Policy assigned to `ResourcePolicy` (pyright checks the structure, C19);
    `test_clearance_mappings_agree` — `atlas.masking.CLEARANCE_FOR_CLASS.values() ==
    access.catalog.CLEARANCES.keys()` and atlas `LABEL_CLASSES` == access `LABEL_CLASSES`.
- [ ] **Step 3: implement.**
  - `atlas/policy.py` (only the protocol; `AtlasCaller` untouched, K4):

    ```python
    from app.atlas.masking import MaskMode
    from app.atlas.scope import RowScope
    class ResourcePolicy(Protocol):
        def allows(self, resource: str) -> bool: ...
        def deny_reason(self, resource: str) -> str: ...
        def row_scope(self, resource: str) -> RowScope | None: ...   # None = all rows
        def has_clearance(self, clearance: str) -> bool: ...
        def mask_mode(self, label_class: str) -> MaskMode | None: ...
    ```

  - `provenance.py`: `build_provenance(..., scope: dict[str, Any] | None = None, masking: dict[str, Any]
    | None = None)`; both keys always present in the output.
  - `tools.py`:
    - `_CallTrace` dataclass + module `ContextVar` (C15), set/reset in `execute()`.
    - `AtlasTools.__init__(..., *, pseudonym_key: str | None = None)` (C13).
    - `_row_scope(entity, resource) -> RowScope | None`: `self._policy.row_scope` (exception ⇒
      `AtlasPolicyError`), then `narrow_scope(scope, _columns(entity))`; `ScopeCompileError` ⇒
      `AtlasAccessDeniedError(label, UNDECLARED or reason)`.
    - `_visible(resource)` becomes `_visible(resource, entity)`: allowed **and** `_row_scope` succeeds;
      `visible_metrics`, `visible_funnels`, `_entity_visible`, `search_atlas` pass the entity.
    - `_get_metric` returns `(metric, entity, scope)`; `_authorize` then `_row_scope`.
    - `_compile(entity, sql, scope) -> CompiledScope` and record into the trace. Apply in
      `query_metric`, `metric_breakdown`, `funnel_analyze` (every step, one scope), and
      `_freshness(entity, scope)`.
    - `metric_breakdown`: after fetch, `mask_breakdown(rows, metric.breakdown_label_class, cleared=...,
      mode=..., key=...)`; add `suppressed_rows` / `others_covers` when set; record masking.
    - `describe_entity` per D3.10: `entity_wide = self._visible(entity_resource(entity), entity)`.
    - `_metric_provenance` and the funnel provenance pass `scope={"restricted": c.restricted,
      "dimensions": list(c.dimensions)}` and `masking`.
    - `_audit`: append `scope=trace.scope, masking=trace.masking` at the **end** of the
      `AtlasAuditLog(...)` call (K4).
  - `__init__.py`: export `MaskMode`, `RowScope`.
- [ ] **Step 4:** `uv run pytest tests/test_atlas_scope.py tests/test_atlas_masking.py
  tests/test_atlas_access.py tests/test_atlas_tools.py tests/test_insights_service.py tests/test_mcp_access.py -q`,
  full gate (`lint-imports` confirms `app.atlas` imports no `app.access`). **Acceptance:** commit
  `feat(atlas): enforce row scopes and field masking`. **Commit after T5, before T9.**

### Task 9: Plugin definitions and seeds

**Files:** modify demo `orders.yaml`, `customers.yaml`; deepsales `accounts.yaml`, `leads.yaml`,
`revenue.yaml`, `tasks.yaml`; `backend/scripts/seed_demo.py`; `backend/tests/conftest.py`;
`backend/tests/test_deepsales_plugin.py`; create `backend/tests/test_demo_scoped_definitions.py`.

- [ ] **Step 1: failing tests** (`test_demo_scoped_definitions.py`, shipped registry, `make_tools`):
  - `test_unscoped_demo_numbers_are_unchanged` — revenue 10500, `orders_count` 49, `b2b_revenue` 7000,
    `new_customers` 21, funnel 100/60/40/25/20 per day ×7 (same as today's tests).
  - `test_channel_scope_gives_3500` (`row_scopes=[("demo/order/*", ({"channel": {"b2c"}},))]`).
  - `test_orders_by_rep_breaks_down_by_rep` (cleared): `{"Aisha Khan": 21, "Omar Haddad": 14,
    "Lina Saab": 14}` (compare as dict; Omar/Lina tie); `query_metric orders_by_rep` = 49.
  - `test_sales_rep_scope` — `{"sales_rep": {"Aisha Khan"}}` ⇒ `orders_by_rep` 21, revenue 2100.
  - `test_every_scoped_demo_query_executes_on_sqlite` — for each scoped demo entity, compile every
    query with a restricted scope and run it (C9).
  - `test_deepsales_scoped_entities` (`test_deepsales_plugin.py`): `scope_catalog()` contains exactly the
    D3.13/C1 rows; every deepsales scoped query compiles and passes `assert_read_only`; the existing
    PII-substring test still passes.
- [ ] **Step 2: implement.**
  - Seed (both `scripts/seed_demo.py` DDL `sales_rep TEXT NOT NULL` and conftest `DEMO_DDL`
    `sales_rep TEXT`): for `i, (channel, …)` in the day's order list: `b2b` ⇒ `"Lina Saab"`; `b2c` ⇒
    `"Aisha Khan"` if `i % 2 == 0` else `"Omar Haddad"`. Per day paid: Aisha 3×100, Omar 2×100, Lina
    2×500. Update the seed script's docstring.
  - demo `order`: `scope_dimensions: {channel: {column: channel, description: ...}, sales_rep: {column:
    sales_rep, self: rep_name, description: ...}}`; `{{scope}}` before `GROUP BY` in every query;
    freshness `... FROM demo_orders WHERE TRUE {{scope}}`; new `orders_by_rep` (unit orders; query =
    paid count; breakdown `SELECT sales_rep AS label, COUNT(*) AS value ... {{scope}} GROUP BY sales_rep
    ORDER BY value DESC LIMIT :limit`; `breakdown_label_class: person_name`). Add `sales_rep` to `fields`.
  - demo `customer`: `segment: {column: segment}`; `customers_total` gets `WHERE TRUE {{scope}}`.
  - demo `checkout`: unchanged.
  - deepsales: `ds_task` `csm: {column: assignee_name, self: csm_name}` (C1); `ds_account` `csm: {column:
    csm_name, self: csm_name}`; `ds_lead` `owner: {column: owner_email, self: csm_email}` (C2);
    `ds_revenue` `csm: {column: c.csm_name, self: csm_name}` with the join on all four queries (C3).
    Every query (metrics, breakdowns, funnel steps, freshness) carries `{{scope}}`.
- [ ] **Step 3:** targeted tests, full gate. **Acceptance:** commit
  `feat(sources): declare scope dimensions on demo and deepsales`.

### Task 6: Admin writes

**Files:** modify `backend/app/access/{admin,startup,schemas,repository,__init__}.py`,
`backend/tests/access/test_admin_grants.py` (the `clearances` rejection case becomes an acceptance
case); create `backend/tests/access/test_admin_scopes.py`, `test_admin_attributes.py`,
`test_admin_label_classes.py`, `test_scope_dimension_sync.py`.

- [ ] **Step 1: failing tests** (service level, `admin_for(db)` / `actor_with(...)` helpers):
  - Scopes (mirror seeded with `mirror_dimensions`): 422 for a scope on `effect=deny`, on a capability,
    on a clearance; an undeclared dimension on `demo/order/*`; a dimension declared by no entity under
    `*`; `$self` on a dimension without `self`; >20 dims, >100 values, value >200 chars, bad key
    (schema validation). Accepted: `*` with `channel` (declared by `demo/order`); `demo/order/revenue`
    with `sales_rep=[$self]`; stored `row_scope` round-trips; `grant.create` change row carries it.
    A scoped grant on a disabled (unmirrored) plugin ⇒ 422. Same (subject, target) scoped + unscoped ⇒ 409.
  - Clearances: `fields:people_names` allow to a group and to a user ⇒ accepted; unknown clearance ⇒
    422; API actor without the clearance granting it ⇒ 403; revoking a clearance deny without holding
    it ⇒ 403; CLI actor ⇒ allowed (C10).
  - Attributes: set/overwrite/delete audited (`attribute.set` / `attribute.delete`, before/after),
    each bumps `policy_version`; no-op set doesn't bump; self ⇒ 409; reserved `email` ⇒ 422 (C11);
    bad key ⇒ 422; value too long ⇒ 422; cross-tenant user ⇒ 404; needs `admin:users` (403 without);
    delete of a missing key ⇒ 404.
  - Label classes: `set_label_class` needs `admin:groups`; `category` ⇒ 422 (C12); bad mode ⇒ 422;
    `bucket_size` 0 or 51 ⇒ 422; audited `label_class.update`; bumps; `list_label_classes` returns both.
  - Scope dimensions: `list_scope_dimensions` with `admin:groups` or `admin:users`; neither ⇒ 403.
  - `test_scope_dimension_sync.py`: sync replaces rows wholesale; running it twice is a no-op;
    removed dimensions disappear; it does **not** bump the version (C8).
- [ ] **Step 2: implement.**
  - `schemas.py`: `GrantCreate.row_scope: dict[str, list[str]] | None = None` with a
    `field_validator` (key regex, 1..20 dims, 1..100 values, each 1..200 chars, de-duplicated, sorted);
    `GrantOut.row_scope: dict[str, list[str]] | None` (append); `AttributePut{value: str =
    Field(min_length=1, max_length=200)}`; `LabelClassPut{mode: Literal["pseudonymise", "suppress",
    "bucket"], bucket_size: int | None = Field(default=None, ge=1, le=50)}`.
  - `admin.py` (new methods appended in their own sections; existing helpers untouched for phase 5's
    mechanical refactor): in `_validated_target` replace the D1 rejection with `_clearance_target`
    (known code; any subject). In `create_grant`: if `payload.row_scope` and (`effect == deny` or
    `target_kind != resource`) ⇒ 422; inside `_write`, `await self._check_scope(target,
    payload.row_scope)` against `repo.scope_dimensions()` (pattern → entities via `patterns.matches`
    on `source/entity`, plus the first two segments of a 3-segment item pattern); C10 check; store
    `row_scope`. `revoke_grant`: C10 check for clearance denies. New: `list_attributes`,
    `set_attribute`, `delete_attribute` (`_not_self_attribute` raises `ConflictError`),
    `list_label_classes`, `set_label_class`, `list_scope_dimensions`. Each write: `_write` →
    change → `_commit` (bump + `rbac_changes`), exactly like `update_group`.
  - `repository.py`: `attribute(user_id, key)`, `list_attributes(user_id)`, `label_class(cls)`,
    `list_label_classes()`, `scope_dimensions()` (rows), `replace_scope_dimensions(rows)` (staged).
  - `startup.py`: `sync_scope_dimensions(db, rows: Iterable[tuple[str, str, str, str | None, str]])`
    — PG advisory lock (reuse `STARTUP_LOCK_KEY`), replace, commit, no bump (C8).
  - `__init__.py`: export `sync_scope_dimensions`.
- [ ] **Step 3:** `uv run pytest tests/access -q`, full gate. **Acceptance:** commit
  `feat(access): scoped grants, clearances, attributes and label classes`.

### Task 7: Admin API, schemas, CLI, preview

**Files:** modify `backend/app/access/{router,schemas,service,cli}.py`; create
`backend/tests/access/test_row_field_api.py`, `backend/tests/access/test_cli_row_field.py`.
These shapes are the phase-5 contract (K3); do not rename fields.

| Route | Capability | Shape |
|---|---|---|
| `POST /api/v1/admin/grants` (existing) | admin:groups / admin:users | `GrantCreate.row_scope: dict[str, list[str]] \| None`; `GrantOut.row_scope` |
| `GET /api/v1/admin/users/{id}/attributes` | admin:users | `list[AttributeOut{key, value, set_by: UUID \| None, set_at}]` |
| `PUT /api/v1/admin/users/{id}/attributes/{key}` | admin:users | `AttributePut{value}` → `AttributeOut` |
| `DELETE /api/v1/admin/users/{id}/attributes/{key}` | admin:users | 204 |
| `GET /api/v1/admin/label-classes` | admin:groups | `list[LabelClassOut{label_class, mode, bucket_size, updated_at}]` |
| `PUT /api/v1/admin/label-classes/{label_class}` | admin:groups | `LabelClassPut{mode, bucket_size?}` → `LabelClassOut` |
| `GET /api/v1/meta/scope-dimensions` | admin:groups or admin:users | `list[ScopeDimensionOut{source, entity, dimension, self_attribute, description}]` |
| `GET /api/v1/meta/capabilities` (existing) | any signed-in | `CatalogOut` + `clearances: list[ClearanceOut{code, description}]`, `label_classes: list[str]`, `mask_modes: list[str]` |
| `GET /api/v1/admin/users/{id}/access` (existing) | admin:users | `EffectiveAccessOut` + `clearances: list[str]`, `allow[].row_scope: dict[str, list[str]] \| None`, `skipped: list[SkippedOut{pattern, grant_id, origin, reason}]`, `decision.row_scope: list[dict[str, list[str]]] \| None` |
| `GET /api/v1/me/access` (existing) | any | `MeAccessOut` + `clearances: list[str]` |

- [ ] **Step 1: failing tests** (`test_row_field_api.py`, through the app client as in
  `test_admin_api.py`): each route's happy path; 403 without the capability; cross-tenant user ⇒ 404 on
  the attribute routes; 422 bodies for a bad scope / bad mode; `/meta/scope-dimensions` lists the
  mirror; `EffectiveAccessOut` for a user with a scoped allow, a skipped `$self` grant and a clearance
  shows all four new fields; `decision.row_scope` is `null` for unrestricted and a list for scoped;
  `/me/access` shows `clearances`; no existing field renamed (assert the full key set).
  `test_cli_row_field.py`: `grant group:csm allow 'deepsales/*' --scope 'csm=$self'` stores the scope;
  `--scope 'country=AE,SA'` parses to two values; repeated `--scope` merges; `--kind clearance`;
  `set-attr`, `unset-attr`, `attrs`, `label-classes`, `label-class person_name bucket --bucket-size 3`,
  `scope-dimensions`; `access <email> --resource demo/order/revenue` prints clearances, skipped grants
  and the row scope. Bad `--scope` (no `=`) ⇒ exit 1 with a message.
- [ ] **Step 2: implement.** Routes stay thin (resolve actor, call `AccessAdmin`, return schema). Path
  `key` validated by the service (422). `EffectiveAccessOut.from_policy` uses `policy.row_scope(resource)`
  for the decision (note in the docstring: this is the policy view; the atlas additionally drops
  dimensions an entity doesn't declare, D3.7). `AccessService.describe` fills `clearances`. CLI
  `_parse_scope(values: list[str]) -> dict[str, list[str]]`; `--kind` choices add `clearance`; new
  subcommands call the T6 methods with `Actor.cli()`; update the module docstring examples (quote
  `'$self'`).
- [ ] **Step 3:** `uv run pytest tests/access -q`, full gate. **Acceptance:** commit
  `feat(access): row and field admin API and CLI`.

### Task 10: Wiring and end to end

**Files:** modify `backend/app/main.py`, `backend/app/config.py`, `backend/app/agent/prompts.py`,
`backend/app/insights/schemas.py`, `backend/.env.example`, `backend/tests/test_prompts.py`,
`backend/tests/test_startup.py`, `backend/tests/test_config.py`; create `backend/tests/test_row_field_e2e.py`.

- [ ] **Step 1: failing tests:**
  - `test_startup.py`: `test_startup_mirrors_scope_dimensions` (after `apply_startup`, the table
    equals `get_registry().scope_catalog()`); the existing "+1 version" test still passes (C8);
    `test_startup_logs_a_missing_pseudonym_key_in_production` (monkeypatched settings, `capture_logs`).
  - `test_config.py`: `atlas_pseudonym_key` defaults to `""` and reads `ATLAS_PSEUDONYM_KEY`.
  - `test_prompts.py`: `test_prompt_says_when_an_answer_is_restricted` and
    `test_prompt_forbids_guessing_hidden_names` (C14).
  - `test_insights_api.py` or a new case: provenance with `scope` / `masking` passes through `ProvenanceOut`.
  - `test_row_field_e2e.py` (spec §13), real `policy_for` + `evaluate()`, shipped demo registry, mirror
    synced, label classes seeded (person_name = suppress), `orders_by_rep` breakdown over the last 7
    full days:
    1. unscoped + `fields:people_names` (via a group clearance grant) ⇒ three named rows (21/14/14);
    2. `demo/order/*` with `sales_rep=[$self]`, attribute `rep_name="Aisha Khan"`, cleared ⇒ one row
       `Aisha Khan: 21`, provenance `restricted: true`;
    3. unscoped, uncleared ⇒ `rows == []`, `suppressed_rows == 3`, `query_metric` still 49;
    4. revoke principal 1's clearance through `AccessAdmin.revoke_grant` ⇒ the next call (new
       `policy_for`) is suppressed — the version bump invalidated the cache;
    5. delete principal 2's `rep_name` ⇒ the grant is skipped ⇒ `orders_by_rep` denied.
- [ ] **Step 2: implement.**
  - `config.py`: append `atlas_pseudonym_key: str = ""` (comment: HMAC key for pseudonymised labels;
    empty ⇒ pseudonymise degrades to suppress). Keep it away from the MCP settings phase 4 removes.
  - `main.py` `apply_startup`: before `prepare_access`, `await sync_scope_dimensions(db,
    get_registry().scope_catalog())` (comment: before the bump, C8); then
    `if settings.environment == "production" and not settings.atlas_pseudonym_key:
    logger.error("atlas.pseudonym_key_missing")`.
  - `prompts.py`: rule 11 — "If a result's provenance says the scope is restricted, say briefly that the
    figure covers only the data the user can see (e.g. 'across the accounts you can see'). If a
    breakdown's labels are pseudonymised, bucketed or suppressed, never guess the hidden names; say
    names are hidden by access settings."
  - `insights/schemas.py`: `ProvenanceScopeOut{restricted: bool, dimensions: list[str]}`,
    `ProvenanceMaskingOut{label_class: str, mode: str}`; `ProvenanceOut.scope / masking` optional.
  - `backend/.env.example`: `ATLAS_PSEUDONYM_KEY=` with a one-line comment (`openssl rand -hex 32`).
- [ ] **Step 3:** targeted tests, full gate. **Acceptance:** commit `feat: wire row and field controls end to end`.

### Task 11: Evals

**Files:** modify `evals/run_evals.py`; create `evals/goldens/row_field.yaml`.

- [ ] **Step 1: runner.** `_policy(user, golden)`: `allow` entries may be strings or `{pattern,
  row_scope}`; optional `clearances: [code]` ⇒ clearance allow grants; optional `attributes: {k: v}`
  merged with built-ins (`email` = `EVAL_EMAIL`, `user_id`); `self_attributes` from
  `get_registry().scope_catalog()`; `label_modes` default `{"person_name": ("suppress", 5),
  "business_name": ("pseudonymise", 5)}`, overridable by `label_modes`. New check `_check_none`:
  `expect_none: [str]` fails if any appears in the answer (case-insensitive); add to `_CHECKS`.
  Update the module docstring.
- [ ] **Step 2: goldens** (`row_field.yaml`):

  ```yaml
  - id: scoped-revenue-b2c
    question: "What was total revenue over the last 7 full days?"
    allow: [{pattern: "demo/order/*", row_scope: {channel: [b2c]}}]
    expect_metric: revenue
    expect_value: 3500
  - id: masked-rep-breakdown
    question: "Break down paid orders by sales rep for the last 7 full days."
    expect_tool: metric_breakdown
    expect_none: ["Aisha", "Omar", "Lina"]
  - id: self-scoped-rep
    question: "How many paid orders were there over the last 7 full days?"
    allow: [{pattern: "demo/order/*", row_scope: {sales_rep: ["$self"]}}]
    attributes: {rep_name: "Aisha Khan"}
    expect_tool: query_metric
    expect_value: 21
  - id: undeclared-scope-is-honest
    question: "What was total revenue over the last 7 full days?"
    allow: [{pattern: "demo/*", row_scope: {region: [AE]}}]
    expect_no_numbers: true
    expect_any: ["access", "admin"]
  ```

- [ ] **Step 3:** reseed the local preview DB (`uv run python scripts/seed_demo.py`, per the local
  preview recipe), then `uv run python ../evals/run_evals.py` — all goldens pass (new and existing);
  record the pass count in the commit body. Gate (`ruff`/`pyright ../evals`). **Acceptance:** commit
  `test(evals): row-scope and masking goldens`.

### Task 12: Contracts, typing, docs

**Files:** modify `backend/pyproject.toml`, `ARCHITECTURE.md`, `CLAUDE.md`, `README.md`,
`docs/specs/2026-10-08-auth-rbac-design.md`.

- [ ] `pyproject.toml`: `strict = [..., "app/atlas/scope.py", "app/atlas/masking.py"]`; fix any strict errors.
- [ ] `ARCHITECTURE.md`: atlas gains `scope.py` / `masking.py` (pure; the only places scope and masking
  happen); D3.12 result-cache rule; `app.atlas` → `app.config` for the pseudonym key (C13).
- [ ] `CLAUDE.md` guardrail 2: provenance also carries scope (dimension names) and masking; guardrail 3/4:
  row scopes come from grants and admin-set attributes, never from the prompt.
- [ ] `README.md` "Access control": a phase-3 subsection — scoped grants, attributes, clearances, label
  classes, CLI examples. **Deploy notes** (in order): set `ATLAS_PSEUDONYM_KEY` in the box's `.env`;
  back up; deploy (migration 0004 runs at start; phase-3 code and 0004 must ship together, D3.3);
  reseed demo (`scripts/seed_demo.py`, adds `sales_rep`); EXPLAIN the `ds_revenue` join queries on the
  box (C3); grant admins their first clearance via the CLI (C10); set `csm_name` (and `csm_email`)
  attributes via `set-attr`; grant group `csm` `deepsales/*` with `--scope 'csm=$self'` (and
  `deepsales/ds_lead/*` `--scope 'owner=$self'` if wanted, C2); verify with `access <email> --resource
  deepsales/ds_task/ds_open_tasks`.
- [ ] Spec §5.5/§5.6/§16: record the as-built differences (numbered `IN` placeholders, not `= ANY`;
  `ds_task.csm` per C1; registry-wide `self` per dimension; `describe_entity` rule; bucket `Others`
  semantics; only two settable label classes; clearance D10 analogue).
- [ ] `make check` green. **Acceptance:** commit `docs: row and field controls`.

---

## Risks

| Risk | Covered by |
|---|---|
| SQL injection via scope values | T2 adversarial tests (values only in params); bandit S608 in ruff |
| Unscoped query in a scoped entity | T1 lint; T8 recording connector |
| `$self` resolves to the wrong attribute | C1 registry-wide `self`; T4, T10 |
| Stale Policy after attribute / label / clearance change | version bumps (T5, T6); T10 revocation step |
| Self-escalation via attributes or clearances | `_not_self_attribute` (T6), C10 |
| Masking bypass (insights, MCP) | masking only inside `AtlasTools` (T8); T10 e2e |
| Missing pseudonym key | degrades to suppress (T3); startup error log (T10) |
| Undeclared dimension fails open | T6 (grant time), T8 (execution + discovery) |
| SQLite vs Postgres divergence | T2/T9 run on SQLite; `test_alembic_postgres` drift + CHECKs |
| `ds_revenue` join cost on the live DB | EXPLAIN on the box before deploy (T12 notes) |
| Merge collisions with phases 4/5 | K2/K4 append-only edits; one owner per shared test file |
