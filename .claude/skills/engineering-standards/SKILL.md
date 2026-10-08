---
name: engineering-standards
description: MANDATORY before writing or modifying any code in ygg-atlas — backend Python (FastAPI, SQLModel, atlas kernel, source plugins, agent), frontend TypeScript/React, tests, migrations, or plugin YAML definitions. Gives the working procedure that places code in the right module and layer, keeps it inside the enforced architecture, and validates it with `make check` before the work is handed to production-code-review.
---

# Engineering standards: how to write code in ygg-atlas

The rules live in `ARCHITECTURE.md` (repo root) and `CLAUDE.md`. This skill is the procedure for
applying them. Machines are the final authority: if `make check` fails, the work is not done.

## Procedure (follow in order, every time)

1. **Read the rules for the area you touch.** The relevant sections of `ARCHITECTURE.md` (§2
   backend, §3 frontend), the `CLAUDE.md` guardrails, and `DESIGN.md` for any UI.
2. **Find what already exists.** Before creating anything, search for similar code:
   `grep -rn "<concept>" backend/app frontend/src`. Reuse or extend an existing abstraction rather
   than adding a parallel one.
3. **Before any repo-wide mechanical change** (reformat, mass rename, dependency bump): run
   `git status` and look for changes you did not make, and check for other live Claude sessions
   in the same repo (`ListAgents`). If either exists, coordinate first and do the work in a
   separate git worktree; never stash, reset or check out someone else's uncommitted work.
4. **Decide ownership.** Use the tables below to pick the exact module and file. If nothing fits,
   stop and say so instead of inventing a new top-level structure. A new top-level package needs
   import-linter contracts in the same change.
5. **Write the failing test first** (TDD). Test behavior through the public interface.
6. **Make the smallest change that passes.** Respect layer direction. Keep edges thin. No
   speculative abstractions, no unrelated refactors, no drive-by renames.
7. **Run the fast loop while working:**
   - Format and auto-fix everything: `make format`
   - Backend types for the files you touched: `cd backend && uv run pyright <files>`
   - Frontend: `make check-frontend` (uses the repo's pnpm invocation from the Makefile)
8. **Run the full gate:** `make check` from the repo root. Fix root causes; never weaken a rule,
   skip a test, or blanket-suppress.
9. **Self-review the diff** (`git diff`) against the anti-pattern list below.
10. **Invoke the `production-code-review` skill** before saying the work is complete.

## Where code goes

### Backend

| You are adding | Put it in |
|---|---|
| An HTTP endpoint | `app/<module>/router.py` (or `app/api/` for existing routes): parse → service → schema |
| Business logic or a use case | `app/<module>/service.py` |
| Database reads or writes | `app/<module>/repository.py` |
| A table | `app/<module>/models.py` (SQLModel, `TIMESTAMP(timezone=True)` on every datetime) |
| A request or response shape | `app/<module>/schemas.py` (Pydantic, separate from models) |
| A business metric, funnel or breakdown | YAML in `app/sources/<plugin>/definitions/`, never Python |
| A new data source | A new plugin package `app/sources/<id>/` (manifest + connector + definitions), added to the plugin independence contract in `backend/pyproject.toml` |
| An agent tool behavior | `app/atlas/tools.py` (the one door to data) |
| A helper used only here | The same module, in a file named for what it does |
| A truly cross-cutting helper | `app/core/<topic>.py`, only with a stable, generic job and several real consumers |

### Frontend

| You are adding | Put it in |
|---|---|
| A screen or flow | `src/features/<name>/` and compose it in `App.tsx` |
| A component used by one feature | That feature (`components/` once it passes about 8 files) |
| A generic primitive used by two or more features | `src/ui/` (check `DESIGN.md` and existing primitives first) |
| An API call or Query hook used by several features | `src/api/` |
| Non-visual app-wide infrastructure | `src/lib/` |

## Anti-patterns (each one is a review failure)

- Business logic or SQL in a router, MCP handler or React page.
- A router importing a repository, `sqlmodel` or `sqlalchemy`.
- A feature importing another feature; `ui/` importing `api/`, `lib/` or features.
- `utils.py`, `helpers.py`, `common.py` or `utils.ts` grab-bags.
- Moving code into `core/` or `ui/` just because two places use it.
- A new abstraction with one caller and no second caller in sight.
- `Any`/`any`, missing annotations, `# type: ignore` or `eslint-disable` without a code and reason.
- Naive datetimes; SQL built from strings with values in them; raw PII selected anywhere.
- Business data reached any way other than an atlas tool (`CLAUDE.md` guardrail 1).
- Tests weakened, skipped or deleted to get green.
- Unrelated changes bundled into the diff.

## Examples

Bad: the route does everything.

```python
@router.post("/groups")
async def create_group(body: dict, db: AsyncSession = Depends(get_db)):
    if not body.get("name"):
        raise HTTPException(400)
    group = Group(name=body["name"])
    db.add(group)
    await db.commit()
    return group
```

Good: the route translates, the service decides, the repository persists.

```python
@router.post("/groups", response_model=GroupOut)
async def create_group(
    payload: GroupCreate,
    service: GroupService = Depends(get_group_service),
    principal: Principal = Depends(get_principal),
) -> GroupOut:
    return await service.create_group(principal, payload)
```

Bad: a page fetches and computes inline.

```tsx
export function OrdersPage() {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => { fetch('/api/v1/orders').then((r) => r.json()).then(setRows); }, []);
  return <table>{rows.map((r) => <tr key={r.id}>{/* 200 lines */}</tr>)}</table>;
}
```

Good: the page composes; data comes through a typed hook; the table owns presentation.

```tsx
export function OrdersPage() {
  const { data: orders = [] } = useOrders();
  return <OrderTable orders={orders} />;
}
```

## Suppressions

Allowed only when the rule is wrong for that one line, with the exact code and a reason:
`# noqa: PLC0415  # optional "ga4" extra` or
`// eslint-disable-next-line react-hooks/exhaustive-deps -- stable per session`.
Never edit `pyproject.toml`, `eslint.config.js` or `tsconfig.json` to relax a rule for your code.
