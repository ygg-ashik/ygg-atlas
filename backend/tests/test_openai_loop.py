"""OpenAI provider loop tests with a fake client — no network."""

from dataclasses import dataclass, field

from app.agent.providers.openai_loop import run_tool_loop


@dataclass
class FakeFunction:
    name: str | None = None
    arguments: str | None = None


@dataclass
class FakeToolCallDelta:
    index: int
    id: str | None = None
    function: FakeFunction | None = None


@dataclass
class FakeDelta:
    content: str | None = None
    tool_calls: list[FakeToolCallDelta] | None = None


@dataclass
class FakeChoice:
    delta: FakeDelta
    finish_reason: str | None = None


@dataclass
class FakeUsage:
    prompt_tokens: int = 10
    completion_tokens: int = 5


@dataclass
class FakeChunk:
    choices: list[FakeChoice] = field(default_factory=list)
    usage: FakeUsage | None = None


class FakeChatStream:
    def __init__(self, chunks: list[FakeChunk]):
        self._chunks = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration from None


class FakeOpenAIClient:
    def __init__(self, rounds: list[list[FakeChunk]]):
        self._rounds = iter(rounds)
        self.requests: list[dict] = []
        outer = self

        class Completions:
            async def create(self, **kwargs):
                outer.requests.append(kwargs)
                return FakeChatStream(next(outer._rounds))

        class Chat:
            completions = Completions()

        self.chat = Chat()


def _tool_round() -> list[FakeChunk]:
    """Streams a query_metric tool call split across chunks (args arrive in pieces)."""
    return [
        FakeChunk(
            choices=[
                FakeChoice(
                    FakeDelta(
                        tool_calls=[
                            FakeToolCallDelta(
                                0,
                                id="call_1",
                                function=FakeFunction(
                                    "query_metric", '{"metric_id": "rev'
                                ),
                            )
                        ]
                    )
                )
            ]
        ),
        FakeChunk(
            choices=[
                FakeChoice(
                    FakeDelta(
                        tool_calls=[
                            FakeToolCallDelta(
                                0,
                                function=FakeFunction(
                                    None,
                                    'enue", "start_date": "2026-01-01", '
                                    '"end_date": "2026-01-07"}',
                                ),
                            )
                        ]
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=FakeUsage(),
        ),
    ]


def _text_round(text: str) -> list[FakeChunk]:
    return [
        FakeChunk(choices=[FakeChoice(FakeDelta(content=text))]),
        FakeChunk(
            choices=[FakeChoice(FakeDelta(), finish_reason="stop")], usage=FakeUsage()
        ),
    ]


async def collect(gen):
    return [e async for e in gen]


async def test_tool_round_then_answer():
    client = FakeOpenAIClient([_tool_round(), _text_round("Revenue was 10,500 AED.")])
    executed: list[tuple[str, dict]] = []

    async def execute_tool(name, args):
        executed.append((name, args))
        return {"value": 10500.0}

    events = await collect(
        run_tool_loop(
            client=client,
            model="gpt-4.1",
            system="system prompt",
            messages=[{"role": "user", "content": "revenue?"}],
            execute_tool=execute_tool,
            max_rounds=6,
        )
    )

    assert executed == [
        (
            "query_metric",
            {
                "metric_id": "revenue",
                "start_date": "2026-01-01",
                "end_date": "2026-01-07",
            },
        )
    ]
    types = [e["type"] for e in events]
    assert "tool_status" in types
    assert types[-1] == "final"
    assert events[-1]["content"] == "Revenue was 10,500 AED."
    assert events[-1]["token_usage"]["input_tokens"] == 20  # two rounds x 10

    # message plumbing: system first, tool result linked by call id
    second_request = client.requests[1]["messages"]
    assert second_request[0]["role"] == "system"
    assert second_request[-1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": '{"value": 10500.0}',
    }


async def test_budget_exhaustion():
    client = FakeOpenAIClient([_tool_round() for _ in range(3)])

    async def execute_tool(name, args):
        return {"value": 1}

    events = await collect(
        run_tool_loop(
            client=client,
            model="gpt-4.1",
            system="s",
            messages=[{"role": "user", "content": "q"}],
            execute_tool=execute_tool,
            max_rounds=3,
        )
    )
    assert events[-1]["type"] == "error"
    assert "budget" in events[-1]["message"].lower()


async def test_plain_text_answer_streams():
    client = FakeOpenAIClient([_text_round("Hello!")])

    async def execute_tool(name, args):  # pragma: no cover - not called
        raise AssertionError("no tool expected")

    events = await collect(
        run_tool_loop(
            client=client,
            model="gpt-4.1",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            execute_tool=execute_tool,
            max_rounds=3,
        )
    )
    assert [e["type"] for e in events] == ["token", "final"]
    assert events[-1]["content"] == "Hello!"
