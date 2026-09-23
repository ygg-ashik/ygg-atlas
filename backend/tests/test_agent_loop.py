"""Agent loop tests with a fake Anthropic client — no network."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.agent.loop import run_chat_turn
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
            [FakeStreamEvent(FakeDelta(b.text)) for b in self._response.content if b.type == "text"]
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

    def stream(self, **kwargs):
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
                content=[FakeTextBlock("Hello! Ask me about revenue.")], stop_reason="end_turn"
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
                        input={"metric_id": "revenue", "start_date": start, "end_date": end},
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
    assert done["provenance"][0]["source"] == "appdb"


async def test_guardrail_blocks_before_model(db):
    session = await _make_session(db)
    client = FakeAnthropicClient([])  # would raise StopIteration if the model were called
    events = await collect(run_chat_turn("u1", session.id, "", [], db, client=client))
    assert events == [{"type": "blocked", "reason": "Empty message"}]


async def test_tool_budget_exhaustion_yields_error(db):
    session = await _make_session(db)
    tool_response = FakeResponse(
        content=[FakeToolUseBlock(id="tu", name="list_metrics", input={})],
        stop_reason="tool_use",
    )
    client = FakeAnthropicClient([tool_response] * 10)  # never stops calling tools
    events = await collect(run_chat_turn("u1", session.id, "loop!", [], db, client=client))
    assert events[-1]["type"] == "error"
    assert "budget" in events[-1]["message"].lower()
