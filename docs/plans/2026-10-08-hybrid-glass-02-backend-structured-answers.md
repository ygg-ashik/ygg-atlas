# Hybrid Glass Track C: Backend Structured Answers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make answers carry structured `blocks`: a **clarify** block (the agent asks with choices instead of guessing) and **artifact** blocks (tables built deterministically from audited tool results). Stream and persist them so the UI (Track D2) can render choice pills and the artifact side panel.

**Architecture:** A new agent *control* tool `ask_clarification` (no data access, not an atlas tool, not exposed over MCP) is offered to the model alongside the atlas tools. `run_chat_turn` intercepts it and records a clarify block. After each atlas tool call, `artifact_from_result` turns `metric_breakdown` / `compare_periods` / `funnel_analyze` results into artifact blocks. These come from tool output, never from LLM text (guardrail #2). Blocks ride on the `done` event and persist in a new `chat_messages.blocks` JSON column, added by an idempotent startup migration.

**Tech Stack:** FastAPI, SQLModel, Anthropic/OpenAI tool loops, pytest (sqlite), evals harness.

**Branch/worktree:** `feature/hybrid-glass-c` · Backend commands from `backend/` with `uv run`.

**Contract:** `docs/plans/2026-10-08-hybrid-glass-00-overview.md` § Shared contracts 1. Field names must match exactly.

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `app/agent/blocks.py` (+ `tests/test_answer_blocks.py`) | Create | `CLARIFY_TOOL` schema, `build_clarify_block`, `artifact_from_result` |
| `app/agent/providers/anthropic_loop.py` | Modify | Accept `tools` parameter |
| `app/agent/providers/openai_loop.py` | Modify | Accept `tools` parameter (convert per call) |
| `app/agent/loop.py` | Modify | Offer clarify tool, collect blocks, add `blocks` to `done` |
| `app/agent/prompts.py` | Modify | Rule 2: prefer `ask_clarification` over guessing |
| `app/models/chat.py` | Modify | `ChatMessage.blocks` JSON column |
| `app/models/migrations.py` (+ test) | Create | Idempotent additive column migration (Postgres) |
| `app/main.py` | Modify | Run additive migrations at startup |
| `app/api/chat.py` | Modify | Persist `blocks` |
| `tests/test_agent_loop.py`, `tests/test_chat_api.py`, `tests/test_openai_loop.py` | Modify | New cases |
| `../evals/run_evals.py`, `../evals/goldens/core_metrics.yaml` | Modify | `expect_clarify`, `expect_artifact` + goldens |
| `../frontend/src/api/chat.ts`, `../frontend/src/api/chat-stream.ts` | Modify | Contract types |

---

### Task 1: Block builders (pure functions)

**Files:** Create `app/agent/blocks.py`, `tests/test_answer_blocks.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_answer_blocks.py
"""Structured answer blocks: built from tool arguments/results, never from LLM prose."""

from app.agent.blocks import CLARIFY_TOOL, artifact_from_result, build_clarify_block

PROV = {"tool": "metric_breakdown", "source": "demo", "metric_id": "revenue",
        "metric_name": "Revenue", "freshness": None, "executed_at": "2026-10-08T00:00:00+00:00"}


def test_clarify_tool_schema_is_a_valid_tool():
    assert CLARIFY_TOOL["name"] == "ask_clarification"
    props = CLARIFY_TOOL["input_schema"]["properties"]
    assert {"question", "options"} <= set(props)


def test_build_clarify_block_keeps_known_metric_ids_only():
    block = build_clarify_block(
        {
            "question": "Which revenue do you mean?",
            "options": [
                {"label": "Corporate revenue", "metric_id": "b2b_revenue"},
                {"label": "All revenue", "metric_id": "revenue"},
                {"label": "Made up", "metric_id": "not_a_metric"},
            ],
        },
        known_metric_ids={"revenue", "b2b_revenue"},
    )
    assert block == {
        "kind": "clarify",
        "question": "Which revenue do you mean?",
        "options": [
            {"label": "Corporate revenue", "metric_id": "b2b_revenue"},
            {"label": "All revenue", "metric_id": "revenue"},
            {"label": "Made up", "metric_id": None},
        ],
    }


def test_build_clarify_block_rejects_bad_shapes():
    assert build_clarify_block({"question": "x", "options": [{"label": "only one"}]}, set()) is None
    assert build_clarify_block({"question": "", "options": [{"label": "a"}, {"label": "b"}]}, set()) is None
    many = [{"label": str(i)} for i in range(6)]
    block = build_clarify_block({"question": "Pick", "options": many}, set())
    assert block is not None and len(block["options"]) == 4  # capped at 4
    blank = build_clarify_block({"question": "Pick", "options": [{"label": " "}, {"label": "b"}]}, set())
    assert blank is None  # fewer than 2 usable labels


def test_breakdown_result_becomes_artifact():
    result = {"metric_id": "revenue", "name": "Revenue", "unit": "AED",
              "rows": [{"label": "b2b", "value": 1000.0}, {"label": "b2c", "value": 500.0}],
              "provenance": [PROV]}
    art = artifact_from_result("metric_breakdown", result, seq=1)
    assert art == {
        "kind": "artifact",
        "id": "metric_breakdown:revenue:1",
        "artifact_type": "breakdown",
        "title": "Revenue: breakdown",
        "unit": "AED",
        "columns": ["Label", "Value"],
        "rows": [["b2b", 1000.0], ["b2c", 500.0]],
        "provenance": PROV,
    }


def test_compare_result_becomes_artifact():
    result = {"metric_id": "revenue", "name": "Revenue", "unit": "AED",
              "period_a": {"start": "2026-09-01", "end": "2026-09-30", "value": 120.0},
              "period_b": {"start": "2026-08-01", "end": "2026-08-31", "value": 100.0},
              "delta": 20.0, "delta_pct": 20.0, "provenance": [PROV]}
    art = artifact_from_result("compare_periods", result, seq=2)
    assert art["artifact_type"] == "comparison"
    assert art["columns"] == ["Period", "Start", "End", "Value"]
    assert art["rows"] == [["A", "2026-09-01", "2026-09-30", 120.0],
                           ["B", "2026-08-01", "2026-08-31", 100.0]]
    assert art["title"] == "Revenue: period comparison (+20.0%)"


def test_funnel_result_becomes_artifact():
    result = {"funnel_id": "checkout_funnel", "name": "Checkout funnel",
              "steps": [{"id": "a", "name": "View", "count": 100.0, "conversion_from_previous_pct": None},
                        {"id": "b", "name": "Cart", "count": 60.0, "conversion_from_previous_pct": 60.0}],
              "provenance": [PROV]}
    art = artifact_from_result("funnel_analyze", result, seq=3)
    assert art["artifact_type"] == "funnel"
    assert art["id"] == "funnel_analyze:checkout_funnel:3"
    assert art["columns"] == ["Step", "Users", "Conversion from previous %"]
    assert art["rows"] == [["View", 100.0, None], ["Cart", 60.0, 60.0]]
    assert art["unit"] == "users"


def test_errors_and_other_tools_produce_no_artifact():
    assert artifact_from_result("metric_breakdown", {"error": "boom"}, seq=1) is None
    assert artifact_from_result("query_metric", {"value": 1.0, "provenance": [PROV]}, seq=1) is None
    assert artifact_from_result("metric_breakdown", {"name": "x", "rows": [], "provenance": []}, seq=1) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_answer_blocks.py -v`
Expected: FAIL, `ModuleNotFoundError: app.agent.blocks`.

- [ ] **Step 3: Implement `app/agent/blocks.py`**

```python
"""Structured answer blocks attached to the `done` event.

- clarify: the agent asks the user to choose instead of guessing (guardrail #1).
- artifact: a table built deterministically from an audited atlas tool result
  (guardrail #2 — numbers come from tool output, never from LLM prose).
"""

from typing import Any

MAX_CLARIFY_OPTIONS = 4

CLARIFY_TOOL = {
    "name": "ask_clarification",
    "description": (
        "Ask the user to choose between 2-4 interpretations when the question is ambiguous or "
        "matches several governed metrics/periods, instead of guessing. Use plain business "
        "labels (never internal ids as labels). After calling it, end your turn with ONE short "
        "sentence restating what you need — do not answer with numbers in the same turn."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The clarifying question to show."},
            "options": {
                "type": "array",
                "minItems": 2,
                "maxItems": MAX_CLARIFY_OPTIONS,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "Business-language choice"},
                        "metric_id": {
                            "type": "string",
                            "description": "Governed metric id this choice maps to, if any",
                        },
                    },
                    "required": ["label"],
                },
            },
        },
        "required": ["question", "options"],
    },
}


def build_clarify_block(arguments: dict[str, Any], known_metric_ids: set[str]) -> dict | None:
    """Validate model-supplied clarify arguments. Unknown metric ids are dropped (never trusted)."""
    question = str(arguments.get("question") or "").strip()
    raw = arguments.get("options") or []
    options: list[dict] = []
    for opt in raw if isinstance(raw, list) else []:
        if not isinstance(opt, dict):
            continue
        label = str(opt.get("label") or "").strip()
        if not label:
            continue
        metric_id = opt.get("metric_id")
        options.append(
            {"label": label, "metric_id": metric_id if metric_id in known_metric_ids else None}
        )
    options = options[:MAX_CLARIFY_OPTIONS]
    if not question or len(options) < 2:
        return None
    return {"kind": "clarify", "question": question, "options": options}


def _first_provenance(result: dict) -> dict | None:
    prov = result.get("provenance") or []
    return prov[0] if prov else None


def artifact_from_result(tool: str, result: dict, seq: int) -> dict | None:
    """Turn a successful table-shaped tool result into an artifact block (or None)."""
    if not isinstance(result, dict) or "error" in result:
        return None
    provenance = _first_provenance(result)
    if provenance is None:
        return None

    if tool == "metric_breakdown":
        rows = [[r.get("label"), r.get("value")] for r in result.get("rows", [])]
        if not rows:
            return None
        return {
            "kind": "artifact",
            "id": f"metric_breakdown:{result.get('metric_id')}:{seq}",
            "artifact_type": "breakdown",
            "title": f"{result.get('name')}: breakdown",
            "unit": result.get("unit") or "",
            "columns": ["Label", "Value"],
            "rows": rows,
            "provenance": provenance,
        }

    if tool == "compare_periods":
        a, b = result.get("period_a") or {}, result.get("period_b") or {}
        pct = result.get("delta_pct")
        suffix = f" ({pct:+.1f}%)" if isinstance(pct, (int, float)) else ""
        return {
            "kind": "artifact",
            "id": f"compare_periods:{result.get('metric_id')}:{seq}",
            "artifact_type": "comparison",
            "title": f"{result.get('name')}: period comparison{suffix}",
            "unit": result.get("unit") or "",
            "columns": ["Period", "Start", "End", "Value"],
            "rows": [
                ["A", a.get("start"), a.get("end"), a.get("value")],
                ["B", b.get("start"), b.get("end"), b.get("value")],
            ],
            "provenance": provenance,
        }

    if tool == "funnel_analyze":
        steps = result.get("steps") or []
        if not steps:
            return None
        return {
            "kind": "artifact",
            "id": f"funnel_analyze:{result.get('funnel_id')}:{seq}",
            "artifact_type": "funnel",
            "title": str(result.get("name")),
            "unit": "users",
            "columns": ["Step", "Users", "Conversion from previous %"],
            "rows": [
                [s.get("name"), s.get("count"), s.get("conversion_from_previous_pct")] for s in steps
            ],
            "provenance": provenance,
        }

    return None
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_answer_blocks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/blocks.py tests/test_answer_blocks.py
git commit -m "feat(agent): clarify + artifact answer block builders"
```

---

### Task 2: Providers accept a `tools` list

**Files:** Modify `app/agent/providers/anthropic_loop.py`, `app/agent/providers/openai_loop.py`, `tests/test_openai_loop.py`

- [ ] **Step 1: Add a failing OpenAI test** (append to `tests/test_openai_loop.py`, reusing that file's fake client helpers. Look at the existing tests in the file for the fake client constructor and mirror it exactly)

```python
async def test_custom_tools_are_converted_to_openai_functions():
    from app.agent.providers.openai_loop import to_openai_tools

    tools = [{"name": "ask_clarification", "description": "d",
              "input_schema": {"type": "object", "properties": {}}}]
    assert to_openai_tools(tools) == [
        {"type": "function",
         "function": {"name": "ask_clarification", "description": "d",
                      "parameters": {"type": "object", "properties": {}}}}
    ]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_openai_loop.py -v -k custom_tools`
Expected: FAIL, `ImportError: cannot import name 'to_openai_tools'`.

- [ ] **Step 3: Implement in `openai_loop.py`**

Replace the module-level `OPENAI_TOOL_SCHEMAS = [...]` with:

```python
def to_openai_tools(tools: list[dict]) -> list[dict]:
    """Anthropic-style tool schemas → OpenAI function tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


OPENAI_TOOL_SCHEMAS = to_openai_tools(ATLAS_TOOL_SCHEMAS)  # kept for existing importers
```

Change the signature and the create call:

```python
async def run_tool_loop(
    client,
    model: str,
    system: str,
    messages: list[dict],
    execute_tool: Callable[[str, dict], Awaitable[dict]],
    max_rounds: int,
    tools: list[dict] | None = None,
) -> AsyncGenerator[dict, None]:
    openai_tools = to_openai_tools(tools) if tools is not None else OPENAI_TOOL_SCHEMAS
    ...
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=openai_tools,
            stream=True,
            stream_options={"include_usage": True},
        )
```

- [ ] **Step 4: Same parameter in `anthropic_loop.py`**

```python
async def run_tool_loop(
    client,
    model: str,
    system: str,
    messages: list[dict],
    execute_tool: Callable[[str, dict], Awaitable[dict]],
    max_rounds: int,
    tools: list[dict] | None = None,
) -> AsyncGenerator[dict, None]:
    tool_schemas = tools if tools is not None else ATLAS_TOOL_SCHEMAS
    ...
        async with client.messages.stream(
            model=model,
            max_tokens=2048,
            system=system,
            messages=messages,
            tools=tool_schemas,
        ) as stream:
```

- [ ] **Step 5: Run provider tests**

Run: `uv run pytest tests/test_openai_loop.py tests/test_agent_loop.py -v`
Expected: PASS (default keeps old behavior).

- [ ] **Step 6: Commit**

```bash
git add app/agent/providers tests/test_openai_loop.py
git commit -m "refactor(agent): providers take an explicit tools list"
```

---

### Task 3: Loop emits blocks on `done`

**Files:** Modify `app/agent/loop.py`, `tests/test_agent_loop.py`

- [ ] **Step 1: Record request kwargs in the fake client** (in `tests/test_agent_loop.py`, replace `FakeMessages`)

```python
class FakeMessages:
    def __init__(self, responses: list[FakeResponse]):
        self._responses = iter(responses)
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(next(self._responses))
```

- [ ] **Step 2: Add failing tests** (append)

```python
async def test_clarify_tool_is_offered_and_becomes_a_block(db):
    session = await _make_session(db)
    client = FakeAnthropicClient(
        [
            FakeResponse(
                content=[
                    FakeToolUseBlock(
                        id="tu_c",
                        name="ask_clarification",
                        input={
                            "question": "Which revenue do you mean?",
                            "options": [
                                {"label": "Corporate revenue", "metric_id": "b2b_revenue"},
                                {"label": "All revenue", "metric_id": "revenue"},
                            ],
                        },
                    )
                ],
                stop_reason="tool_use",
            ),
            FakeResponse(content=[FakeTextBlock("Which revenue do you mean?")], stop_reason="end_turn"),
        ]
    )
    events = await collect(run_chat_turn("u1", session.id, "how is revenue?", [], db, client=client))

    offered = {t["name"] for t in client.messages.calls[0]["tools"]}
    assert "ask_clarification" in offered and "query_metric" in offered

    done = events[-1]
    assert done["type"] == "done"
    assert done["blocks"] == [
        {
            "kind": "clarify",
            "question": "Which revenue do you mean?",
            "options": [
                {"label": "Corporate revenue", "metric_id": "b2b_revenue"},
                {"label": "All revenue", "metric_id": "revenue"},
            ],
        }
    ]
    assert done["provenance"] == []  # clarification touches no data


async def test_clarify_tool_is_not_audited(db):
    from sqlmodel import select

    from app.models.audit import AtlasAuditLog

    session = await _make_session(db)
    client = FakeAnthropicClient(
        [
            FakeResponse(
                content=[FakeToolUseBlock(id="c", name="ask_clarification",
                                          input={"question": "Q?", "options": [{"label": "a"}, {"label": "b"}]})],
                stop_reason="tool_use",
            ),
            FakeResponse(content=[FakeTextBlock("Q?")], stop_reason="end_turn"),
        ]
    )
    await collect(run_chat_turn("u1", session.id, "q", [], db, client=client))
    rows = (await db.execute(select(AtlasAuditLog))).scalars().all()
    assert all(r.tool != "ask_clarification" for r in rows)


async def test_breakdown_result_becomes_artifact_block(db):
    session = await _make_session(db)
    today = datetime.now(UTC).date()
    start = (today - timedelta(days=7)).isoformat()
    end = (today - timedelta(days=1)).isoformat()
    client = FakeAnthropicClient(
        [
            FakeResponse(
                content=[FakeToolUseBlock(id="b", name="metric_breakdown",
                                          input={"metric_id": "revenue", "start_date": start, "end_date": end})],
                stop_reason="tool_use",
            ),
            FakeResponse(content=[FakeTextBlock("Here is the split.")], stop_reason="end_turn"),
        ]
    )
    events = await collect(run_chat_turn("u1", session.id, "split revenue", [], db, client=client))
    blocks = events[-1]["blocks"]
    assert len(blocks) == 1
    art = blocks[0]
    assert art["kind"] == "artifact" and art["artifact_type"] == "breakdown"
    assert art["id"] == "metric_breakdown:revenue:1"
    assert art["provenance"]["metric_id"] == "revenue"
    assert art["rows"]  # seeded demo data has channels


async def test_plain_answer_has_empty_blocks(db):
    session = await _make_session(db)
    client = FakeAnthropicClient([FakeResponse(content=[FakeTextBlock("Hi")], stop_reason="end_turn")])
    events = await collect(run_chat_turn("u1", session.id, "hi", [], db, client=client))
    assert events[-1]["blocks"] == []
```

Check that `AtlasAuditLog` has a `tool` attribute: `grep -n "tool" app/models/audit.py`. Adjust the attribute name in the test if it differs.

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_agent_loop.py -v`
Expected: the 4 new tests FAIL (no `blocks` key / clarify not offered).

- [ ] **Step 4: Implement in `app/agent/loop.py`**

Update the module docstring's done line to `{type: 'done', content, provenance, blocks, model, token_usage}`. Add imports:

```python
from app.agent.blocks import CLARIFY_TOOL, artifact_from_result, build_clarify_block
from app.atlas import ATLAS_TOOL_SCHEMAS, AtlasTools
```

(replace the existing `from app.atlas import AtlasTools`). Replace the `execute_tool` closure and the provider call:

```python
    provenance: list[dict] = []
    blocks: list[dict] = []
    artifact_seq = 0

    async def execute_tool(name: str, arguments: dict) -> dict:
        nonlocal artifact_seq
        if name == CLARIFY_TOOL["name"]:
            # Control tool: no data access, so not an atlas execution and not audited.
            block = build_clarify_block(arguments, set(tools.registry.metrics))
            if block is None:
                return {"error": "Provide a question and 2-4 options with non-empty labels."}
            if not any(b["kind"] == "clarify" for b in blocks):
                blocks.append(block)
            return {"status": "shown_to_user", "instruction": "End your turn with one short sentence."}

        result = await tools.execute(name, arguments)
        if isinstance(result, dict) and result.get("provenance"):
            provenance.extend(result["provenance"])
        artifact = artifact_from_result(name, result, seq=artifact_seq + 1)
        if artifact is not None:
            artifact_seq += 1
            blocks.append(artifact)
        return result
```

and in the provider call pass `tools=[*ATLAS_TOOL_SCHEMAS, CLARIFY_TOOL],`. In the `final` branch add `"blocks": blocks,` to the yielded dict (after `"provenance": provenance,`).

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_agent_loop.py tests/test_answer_blocks.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/agent/loop.py tests/test_agent_loop.py
git commit -m "feat(agent): stream clarify + artifact blocks on done"
```

---

### Task 4: Persist blocks (column + additive migration)

**Files:** Modify `app/models/chat.py`, `app/main.py`, `app/api/chat.py`, `tests/test_chat_api.py`; Create `app/models/migrations.py`, `tests/test_migrations.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_migrations.py
from app.models.migrations import ADDITIVE_COLUMNS, apply_additive_migrations


class _Dialect:
    def __init__(self, name):
        self.name = name


class _Conn:
    def __init__(self, dialect):
        self.dialect = _Dialect(dialect)
        self.sql: list[str] = []

    async def execute(self, statement):
        self.sql.append(str(statement))


async def test_postgres_adds_columns_idempotently():
    conn = _Conn("postgresql")
    await apply_additive_migrations(conn)
    assert "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS blocks JSON" in conn.sql
    assert len(conn.sql) == len(ADDITIVE_COLUMNS)


async def test_sqlite_is_a_noop_because_create_all_builds_fresh_schemas():
    conn = _Conn("sqlite")
    await apply_additive_migrations(conn)
    assert conn.sql == []
```

Append to `tests/test_chat_api.py`: change the fake `done` event in the `api` fixture to include
`"blocks": [{"kind": "clarify", "question": "Which?", "options": [{"label": "A", "metric_id": None}, {"label": "B", "metric_id": None}]}],`, then add:

```python
async def test_blocks_are_streamed_and_persisted(api):
    session = (await api.post("/api/v1/chat/sessions", json={})).json()
    resp = await api.post(f"/api/v1/chat/sessions/{session['id']}/messages", json={"content": "revenue?"})
    events = [json.loads(l[6:]) for l in resp.text.splitlines() if l.startswith("data: ")]
    assert events[-1]["blocks"][0]["kind"] == "clarify"
    messages = (await api.get(f"/api/v1/chat/sessions/{session['id']}/messages")).json()
    assert messages[1]["blocks"][0]["question"] == "Which?"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_migrations.py tests/test_chat_api.py -v`
Expected: FAIL (module missing; `blocks` absent from persisted message).

- [ ] **Step 3: Implement**

`app/models/migrations.py`:
```python
"""Additive, idempotent schema changes for databases created before a column existed.

The MVP uses SQLModel.create_all (no Alembic yet). create_all never alters existing
tables, so new nullable columns are added here. Postgres only; fresh sqlite test
schemas already have every column.
"""

from sqlalchemy import text

ADDITIVE_COLUMNS: list[tuple[str, str, str]] = [
    ("chat_messages", "blocks", "JSON"),
]


async def apply_additive_migrations(conn) -> None:
    if conn.dialect.name != "postgresql":
        return
    for table, column, sql_type in ADDITIVE_COLUMNS:
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {sql_type}"))
```

`app/models/chat.py`: add to `ChatMessage` after `provenance`:
```python
    blocks: list | None = Field(default=None, sa_column=Column(JSON))  # clarify/artifact blocks
```

`app/main.py` lifespan, after `create_all`:
```python
    async with get_engine().begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await apply_additive_migrations(conn)
```
with `from app.models.migrations import apply_additive_migrations` at the top.

`app/api/chat.py`: in the `done` branch, add `blocks=event.get("blocks") or None,` to the `ChatMessage(...)` constructor.

- [ ] **Step 4: Run tests**

Run: `uv run pytest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models app/main.py app/api/chat.py tests/test_migrations.py tests/test_chat_api.py
git commit -m "feat(chat): persist answer blocks with additive migration"
```

---

### Task 5: Prompt rule + golden coverage (guardrail #6)

**Files:** Modify `app/agent/prompts.py`, `../evals/run_evals.py`, `../evals/goldens/core_metrics.yaml`

- [ ] **Step 1: Update prompt rule 2** (replace the sentence ending "…or ask ONE clarifying question.")

```
offer the closest questions you CAN answer from the catalog. If the question is ambiguous between \
several governed metrics or periods, call ask_clarification with 2-4 business-language options \
instead of guessing (at most once per turn), then end your turn with one short sentence.
```

- [ ] **Step 2: Teach the harness about blocks** (`../evals/run_evals.py`)

In `_run_question` capture blocks: initialise `blocks: list[dict] = []`, set `blocks = event.get("blocks", [])` in the `done` branch, and return `answer, tools_used, provenance, blocks`. Update the call site in `main()`:
`answer, tools_used, provenance, blocks = await _run_question(golden["question"])` and
`failures = _check(golden, answer, tools_used, provenance, blocks)`. Extend `_check`'s signature with `blocks: list[dict]` and append before `return failures`:

```python
    if golden.get("expect_clarify"):
        if not any(b.get("kind") == "clarify" for b in blocks):
            failures.append("expected a clarify block (ask_clarification), got none")

    if artifact_type := golden.get("expect_artifact"):
        kinds = [b.get("artifact_type") for b in blocks if b.get("kind") == "artifact"]
        if artifact_type not in kinds:
            failures.append(f"expected a '{artifact_type}' artifact block; got {kinds}")
```

Document the two new fields in the header comment of `core_metrics.yaml`:
```
#   expect_clarify:      answer must carry a clarify block (asked instead of guessing)
#   expect_artifact:     answer must carry an artifact block of this type (breakdown|comparison|funnel)
```

- [ ] **Step 3: Add goldens** (append to `../evals/goldens/core_metrics.yaml`)

```yaml
- id: clarify-ambiguous-sales
  question: "How did sales do?"
  expect_clarify: true
  expect_no_numbers: true

- id: artifact-revenue-breakdown
  question: "Break down revenue over the last 7 full days."
  expect_tool: metric_breakdown
  expect_metric: revenue
  expect_artifact: breakdown

- id: artifact-checkout-funnel
  question: "Show the checkout funnel for the last 7 full days."
  expect_tool: funnel_analyze
  expect_metric: checkout_funnel
  expect_artifact: funnel
```

- [ ] **Step 4: Run evals (needs an LLM key + seeded demo DB)**

Run: `uv run python ../evals/run_evals.py`
Expected: all goldens pass, including the 3 new ones. If `clarify-ambiguous-sales` fails because the model answers with a default metric, tighten the tool description wording (Task 1 `CLARIFY_TOOL.description`) rather than the golden, then re-run.

- [ ] **Step 5: Lint + full tests**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest --cov=app`
Expected: PASS, coverage on `app/agent/blocks.py` and `app/models/migrations.py` ≥ 80%.

- [ ] **Step 6: Commit**

```bash
git add app/agent/prompts.py ../evals
git commit -m "feat(agent): clarify-over-guess prompt rule + block goldens"
```

---

### Task 6: Frontend contract types

**Files:** Modify `../frontend/src/api/chat.ts`, `../frontend/src/api/chat-stream.ts`, `../frontend/src/api/chat-stream.test.ts`

- [ ] **Step 1: Failing test** (append to `chat-stream.test.ts` inside `describe('parseSseChunk')`)

```ts
  it('parses a done event with answer blocks', () => {
    const done = {
      type: 'done',
      content: 'Which revenue?',
      provenance: [],
      blocks: [{ kind: 'clarify', question: 'Which revenue?', options: [{ label: 'A', metric_id: null }, { label: 'B', metric_id: 'revenue' }] }],
      message_id: 'm1',
    };
    const { events } = parseSseChunk(`data: ${JSON.stringify(done)}\n\n`);
    expect(events).toEqual([done]);
  });
```

- [ ] **Step 2: Add types to `chat.ts`** (after `Provenance`)

```ts
export interface ClarifyOption {
  label: string;
  metric_id?: string | null;
}
export interface ClarifyBlock {
  kind: 'clarify';
  question: string;
  options: ClarifyOption[];
}
export interface ArtifactBlock {
  kind: 'artifact';
  id: string;
  artifact_type: 'breakdown' | 'comparison' | 'funnel';
  title: string;
  unit: string;
  columns: string[];
  rows: (string | number | null)[][];
  provenance: Provenance;
}
export type AnswerBlock = ClarifyBlock | ArtifactBlock;
```
and add `blocks?: AnswerBlock[] | null;` to `ChatMessage`.

- [ ] **Step 3: Extend the `done` variant in `chat-stream.ts`**

```ts
  | {
      type: 'done';
      content: string;
      provenance: Provenance[];
      blocks?: AnswerBlock[];
      message_id?: string;
      model?: string;
    }
```
and `import type { AnswerBlock, Provenance } from './chat';`.

- [ ] **Step 4: Run frontend checks**

Run: `cd ../frontend && corepack pnpm test && corepack pnpm typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ../frontend/src/api
git commit -m "feat(api): AnswerBlock contract types for the chat stream"
```
