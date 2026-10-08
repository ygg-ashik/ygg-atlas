"""Agent loop tests with a fake Anthropic client — no network."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.agent.loop import run_chat_turn
from app.models.audit import AtlasAuditLog
from app.models.chat import ChatSession


@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 20


@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class FakeResponse:
    content: list
    stop_reason: str
    usage: FakeUsage = field(default_factory=FakeUsage)


@dataclass
class FakeDelta:
    text: str
    type: str = "text_delta"


@dataclass
class FakeStreamEvent:
    delta: FakeDelta
    type: str = "content_block_delta"


class FakeStream:
    def __init__(self, response: FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def __aiter__(self):
        self._events = iter(
            [
                FakeStreamEvent(FakeDelta(b.text))
                for b in self._response.content
                if b.type == "text"
            ]
        )
        return self

    async def __anext__(self):
        try:
            return next(self._events)
        except StopIteration:
            raise StopAsyncIteration from None

    async def get_final_message(self):
        return self._response


class FakeMessages:
    def __init__(self, responses: list[FakeResponse]):
        self._responses = iter(responses)
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(next(self._responses))


class FakeAnthropicClient:
    def __init__(self, responses: list[FakeResponse]):
        self.messages = FakeMessages(responses)


async def _make_session(db, uid="u1") -> ChatSession:
    session = ChatSession(user_uid=uid, user_email=f"{uid}@yougotagift.com")
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def collect(gen):
    return [event async for event in gen]


async def test_plain_answer_streams_and_finishes(db):
    session = await _make_session(db)
    client = FakeAnthropicClient(
        [
            FakeResponse(
                content=[FakeTextBlock("Hello! Ask me about revenue.")],
                stop_reason="end_turn",
            )
        ]
    )
    events = await collect(run_chat_turn("u1", session.id, "hi", [], db, client=client))
    types = [e["type"] for e in events]
    assert "token" in types
    assert types[-1] == "done"
    assert events[-1]["content"] == "Hello! Ask me about revenue."
    assert events[-1]["provenance"] == []


async def test_tool_round_collects_provenance(db):
    session = await _make_session(db)
    today = datetime.now(UTC).date()
    start = (today - timedelta(days=7)).isoformat()
    end = (today - timedelta(days=1)).isoformat()

    client = FakeAnthropicClient(
        [
            FakeResponse(
                content=[
                    FakeToolUseBlock(
                        id="tu_1",
                        name="query_metric",
                        input={
                            "metric_id": "revenue",
                            "start_date": start,
                            "end_date": end,
                        },
                    )
                ],
                stop_reason="tool_use",
            ),
            FakeResponse(
                content=[FakeTextBlock("Revenue last week was 10,500 AED.")],
                stop_reason="end_turn",
            ),
        ]
    )
    events = await collect(
        run_chat_turn("u1", session.id, "revenue last week?", [], db, client=client)
    )
    types = [e["type"] for e in events]
    assert "tool_status" in types
    done = events[-1]
    assert done["type"] == "done"
    assert done["provenance"][0]["metric_id"] == "revenue"
    assert done["provenance"][0]["source"] == "demo"


async def test_guardrail_blocks_before_model(db):
    session = await _make_session(db)
    # An empty script would raise StopIteration if the model were ever called.
    client = FakeAnthropicClient([])
    events = await collect(run_chat_turn("u1", session.id, "", [], db, client=client))
    assert events == [{"type": "blocked", "reason": "Empty message"}]


async def test_tool_budget_exhaustion_yields_error(db):
    session = await _make_session(db)
    tool_response = FakeResponse(
        content=[FakeToolUseBlock(id="tu", name="list_metrics", input={})],
        stop_reason="tool_use",
    )
    client = FakeAnthropicClient([tool_response] * 10)  # never stops calling tools
    events = await collect(
        run_chat_turn("u1", session.id, "loop!", [], db, client=client)
    )
    assert events[-1]["type"] == "error"
    assert "budget" in events[-1]["message"].lower()


def _clarify_call(question: str, options: list[dict]) -> FakeResponse:
    return FakeResponse(
        content=[
            FakeToolUseBlock(
                id="tu_c",
                name="ask_clarification",
                input={"question": question, "options": options},
            )
        ],
        stop_reason="tool_use",
    )


def _text(text: str) -> FakeResponse:
    return FakeResponse(content=[FakeTextBlock(text)], stop_reason="end_turn")


async def test_clarify_tool_is_offered_and_becomes_a_block(db):
    session = await _make_session(db)
    options = [
        {"label": "Corporate revenue", "metric_id": "b2b_revenue"},
        {"label": "All revenue", "metric_id": "revenue"},
    ]
    client = FakeAnthropicClient(
        [
            _clarify_call("Which revenue do you mean?", options),
            _text("Which revenue do you mean?"),
        ]
    )
    events = await collect(
        run_chat_turn("u1", session.id, "how is revenue?", [], db, client=client)
    )

    offered = {t["name"] for t in client.messages.calls[0]["tools"]}
    assert "ask_clarification" in offered
    assert "query_metric" in offered

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
    session = await _make_session(db)
    client = FakeAnthropicClient(
        [_clarify_call("Q?", [{"label": "a"}, {"label": "b"}]), _text("Q?")]
    )
    await collect(run_chat_turn("u1", session.id, "q", [], db, client=client))
    rows = (await db.execute(select(AtlasAuditLog))).scalars().all()
    assert all(r.tool != "ask_clarification" for r in rows)


async def test_invalid_clarify_returns_error_to_model_and_no_block(db):
    session = await _make_session(db)
    client = FakeAnthropicClient(
        [_clarify_call("Q?", [{"label": "only one"}]), _text("Sorry.")]
    )
    events = await collect(run_chat_turn("u1", session.id, "q", [], db, client=client))
    assert events[-1]["blocks"] == []
    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert "error" in tool_result["content"]


async def test_only_first_clarify_block_is_kept(db):
    session = await _make_session(db)
    client = FakeAnthropicClient(
        [
            _clarify_call("First?", [{"label": "a"}, {"label": "b"}]),
            _clarify_call("Second?", [{"label": "c"}, {"label": "d"}]),
            _text("First?"),
        ]
    )
    events = await collect(run_chat_turn("u1", session.id, "q", [], db, client=client))
    assert [b["question"] for b in events[-1]["blocks"]] == ["First?"]


async def test_breakdown_result_becomes_artifact_block(db):
    session = await _make_session(db)
    today = datetime.now(UTC).date()
    start = (today - timedelta(days=7)).isoformat()
    end = (today - timedelta(days=1)).isoformat()
    client = FakeAnthropicClient(
        [
            FakeResponse(
                content=[
                    FakeToolUseBlock(
                        id="b",
                        name="metric_breakdown",
                        input={
                            "metric_id": "revenue",
                            "start_date": start,
                            "end_date": end,
                        },
                    )
                ],
                stop_reason="tool_use",
            ),
            _text("Here is the split."),
        ]
    )
    events = await collect(
        run_chat_turn("u1", session.id, "split revenue", [], db, client=client)
    )
    blocks = events[-1]["blocks"]
    assert len(blocks) == 1
    art = blocks[0]
    assert art["kind"] == "artifact"
    assert art["artifact_type"] == "breakdown"
    assert art["id"] == "metric_breakdown:revenue:1"
    assert art["provenance"]["metric_id"] == "revenue"
    assert art["rows"]  # seeded demo data has channels


async def test_plain_answer_has_empty_blocks(db):
    session = await _make_session(db)
    client = FakeAnthropicClient([_text("Hi")])
    events = await collect(run_chat_turn("u1", session.id, "hi", [], db, client=client))
    assert events[-1]["blocks"] == []
