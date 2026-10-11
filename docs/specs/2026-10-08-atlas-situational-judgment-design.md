# Situational judgment: sense before you act

**Date:** 2026-10-08 · **Status:** Approved for spec · **Depends on:** MVP design, plugin
architecture, auth/RBAC design · **Roadmap:** phase A ships with or before P1; phase C with P4

## 1. Problem

A good analyst does not just read a number. Before trusting it, they check whether the data is
fresh, whether something changed underneath it, and whether two sources disagree. Before acting
(sending an alert, launching a trigger, changing a budget), they check who else is acting and how
much damage a mistake would do.

Atlas today does none of this. It returns "signups fell 40% year on year" even when that
comparison crosses a change in how signups were recorded. The EMAPI discovery found several such
traps in the users database alone (§6).

## 2. Principle

> **Procedure is the floor; model judgment is the layer on top.**

The agent's own judgment is useful but probabilistic: it can notice a problem, and it can also
miss it. Every check in this spec is therefore a **guaranteed, deterministic step** that runs
whether or not the model thinks of it. The model then explains, adds nuance, and asks good
questions on top of a floor that never moves.

## 3. Components

### 3.1 Confounder registry (part of each source plugin)

Known traps in the data are declared next to the metrics they affect, reviewed like code, and
linted at load:

```yaml
# app/sources/ecom_users/definitions/confounders.yaml  (ecom_users is the planned plugin)
confounders:
  - id: users_id_cutover_2025_05
    kind: definition_change        # definition_change | bulk_event | retention_window |
                                   # dead_field | partial_coverage | outage
    affects: [ecom_users/user/*]   # resource paths, same syntax as RBAC grants
    window: { end: 2025-05-31 }    # open start: everything before the cutover
    severity: blocking             # blocking | warning | info
    summary: >
      Before June 2025 about 40–60% of allocated user ids do not survive, after it nearly all
      do. Signup counts before and after the change are not comparable.
    guidance: split_at_boundary    # split_at_boundary | exclude_window | annotate | refuse
```

- **Lint:** every `affects` path must match existing resources, every id must be unique, and
  `window` must be ordered.
- **Owners:** the plugin owner adds an entry when a trap is found. Every discovery finding of this
  kind becomes an entry.

### 3.2 Freshness thresholds

Each entity already declares a `freshness_query`. It gains `stale_after` (e.g. `26h`). A result
older than that is itself a confounder: `kind: stale`, severity `warning`, generated at query time.

### 3.3 Pre-answer preflight (control-plane hook)

After every atlas tool call and before the final answer:

1. For each metric result, look up confounders whose `affects` matches the resource and whose
   `window` overlaps the queried date range (or the comparison's ranges).
2. Attach them to the result as structured **caveats** (`id`, `severity`, `summary`, `guidance`),
   carried in provenance alongside source and freshness.
3. Apply `guidance` mechanically where it is safe: `refuse` blocks the metric for that range with
   an honest message. `split_at_boundary` makes `compare_periods` report each side of the boundary
   separately instead of one misleading delta.
4. **Grounding check extension:** an answer that uses a result carrying a `blocking` caveat must
   state it. The existing number-grounding verifier (P1) checks that every blocking caveat id is
   acknowledged, and regenerates the answer otherwise. Until that verifier exists, phase A
   enforces acknowledgement with a system-prompt rule plus goldens (§5), and the UI chips make
   every caveat visible even if the prose omits it.
5. The UI shows caveats as chips next to the provenance chips, in the warning colour from
   `DESIGN.md`.

### 3.4 Contradiction detection

Metrics declare an optional `concept` (e.g. `revenue_aed`, `active_users`). When one turn
retrieves the same concept from two sources, and the values differ by more than the concept's
declared `tolerance` (e.g. 2%), the preflight adds a `conflict` caveat naming both provenances.
The agent reports the disagreement and both numbers. It never silently picks one.

### 3.5 Pre-action preflight (phase C, with P4 actions)

Every action atlas can take is classified by **blast radius**:

| Level | Action | Default decision |
|---|---|---|
| L0 | Answer a question | proceed |
| L1 | Internal alert or report to staff | proceed with notice |
| L2 | Message customers (triggers, campaigns) | require approval |
| L3 | Change an external system (ads budgets, configs) | require approval and a spend cap |

Before any L1+ action, the preflight gathers evidence and can only **raise** the level, never
lower it:

| Check | Raises to |
|---|---|
| A blocking caveat applies to the data behind the action | hold |
| Data is stale | hold |
| Another active campaign, schedule or atlas job targets an overlapping audience | require approval (L2+) or proceed with notice (L1) |
| A relevant configuration or admin change happened in the last 24h (admin log, deploys) | require approval |
| Suppression segment, consent store or spend cap unavailable | hold (fail closed) |

The decision (proceed, proceed with notice, require approval, hold) and the evidence behind it are
recorded as session events (P0) and shown on the review card the user approves.

### 3.6 Coordination registry

Every scheduled atlas job, trigger and campaign records its owner, target audience definition
and active window. This is the "who else is acting" lookup the pre-action preflight uses: the
same role `ListAgents` played for the engineering session that inspired this spec.

## 4. Where it lives

| Piece | Module |
|---|---|
| Confounder schema, loading, lint | `app/atlas/confounders.py` (registry extension) |
| Caveat attachment and `split_at_boundary` | `app/atlas/tools.py` via a preflight service |
| Pre-answer hook and grounding extension | `app/agent/preflight.py` (control-plane hook) |
| Pre-action preflight and blast-radius policy | `app/actions/` (new module, phase C) |
| Coordination registry | `app/actions/registry` tables (phase C) |

All follow `ARCHITECTURE.md`: router, service and repository layers, import-linter contracts
updated in the same change.

## 5. Tests and evals

- **Unit:** window overlap, path matching, severity ordering, the guidance behaviours,
  escalation-only decisions in the action preflight (a check can never lower a level).
- **Goldens:**
  - "How did monthly signups change from 2024 to 2026?" must mention the May 2025 cutover and
    must not report one year-on-year delta across it.
  - "Is blacklist fraud growing?" must attribute the June and August 2026 spikes to bulk imports
    (ships with the `ecom_users` blacklist metric).
  - A deliberately stale fixture must produce a freshness caveat.
  - A two-source revenue conflict must report both numbers.
- **Action preflight:** a trigger on an audience already targeted by a running campaign must not
  auto-run.

## 6. Seed confounders from the EMAPI discovery (`ygag_ecom_users_db`)

Evidence and SQL: `docs/discovery/2026-09-29-emapi/profiles/users.md`.

| id | kind | Window | Effect |
|---|---|---|---|
| `users_id_cutover_2025_05` | definition_change | until 2025-05-31 | 37–62% of each month's ids missing before, under 1% after. Signup counts across it are not comparable |
| `users_is_app_user_from_2024_08` | definition_change | until 2024-07-31 | `is_app_user` share jumps from 18% (Jun 2024) to 84% (Aug 2024): app-vs-web before then is not comparable |
| `users_type_dead_2023_10` | dead_field | from 2023-11-01 | `type` (signup method) only populated until Oct 2023 |
| `users_social_ids_dead_2024_12` | dead_field | from 2024-12-01 | Social IdP ids empty since Dec 2024; social signups are unrecorded, not zero |
| `users_last_login_dead` | dead_field | from 2024-01-01 | `last_login` abandoned; use issued tokens for login activity |
| `users_otp_retention_31d` | retention_window | rolling 31 days | OTP/2FA tables keep about 31 days; no longer history exists |
| `users_tokens_from_2026_07_30` | partial_coverage | until 2026-07-29 | Issued-token history is effectively complete only from 2026-07-30 (web from 2026-08-29) |
| `users_blacklist_bulk_2026_06` | bulk_event | June 2026 | Blacklist spike is a bulk admin import, not organic detection |
| `users_blacklist_bulk_2026_08` | bulk_event | August 2026 | Same (797 emails added in 38 minutes on 2026-08-25) |

## 7. Rollout

| Phase | Delivers | Ready |
|---|---|---|
| A | Confounder registry and lint, freshness thresholds, pre-answer caveats, `split_at_boundary`, caveat chips, the §6 seeds, goldens | With the `ecom_users` plugin; before or with P1 |
| B | Contradiction detection (`concept`, `tolerance`) | Once two sources share a concept (e.g. revenue from orders and DeepSales) |
| C | Pre-action preflight, blast-radius policy, coordination registry, review card | With P4 actions |

## 8. Out of scope

Automatic discovery of new confounders (anomaly detection may *suggest* entries later; a human
adds them). Statistical correction of affected numbers: atlas reports and splits, it does not
"fix" data.
