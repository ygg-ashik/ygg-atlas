"""In-process sliding-window rate limits (plan Task 7, D16)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.types import Receive, Scope, Send
from structlog.testing import capture_logs

from app.mcp.ratelimit import (
    AUTHORIZE,
    BEARER_FAILURES,
    CONSENT,
    MCP_CALLS,
    REGISTER,
    REVOKE,
    TOKEN,
    FailedBearerGuard,
    PrincipalRateLimit,
    RateDecision,
    RateLimitedEndpoint,
    RateLimitPolicy,
    SlidingWindowLimiter,
    limiter,
    rate_limit,
    reset_limiters,
    source_key,
    too_many_requests,
)

RAW_TOKEN = "atl_pat_" + "s3cr3t" * 7


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> Iterator[FakeClock]:
    fake = FakeClock()
    reset_limiters(clock=fake)
    yield fake
    reset_limiters()


def _small(limit: int = 3, window: int = 10) -> RateLimitPolicy:
    return RateLimitPolicy("test", limit, window)


async def _status_app(scope: Scope, receive: Receive, send: Send) -> None:
    """Answers 401 when the path is /deny, else 200."""
    status = 401 if scope["path"] == "/deny" else 200
    await PlainTextResponse("x", status_code=status)(scope, receive, send)


PUBLIC_PEER = "8.8.4.4"  # a public address: per-source limits key it as itself


def _client(app: object, peer: str = PUBLIC_PEER) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, client=(peer, 4321)),  # type: ignore[arg-type]  # ASGITransport accepts any ASGI callable
        base_url="http://test",
    )


# --- the limiter ------------------------------------------------------------


def test_allows_up_to_the_limit_then_refuses(clock: FakeClock) -> None:
    lim = SlidingWindowLimiter(_small(3), clock=clock)
    assert [lim.hit("k").allowed for _ in range(3)] == [True, True, True]
    refused = lim.hit("k")
    assert refused == RateDecision(allowed=False, retry_after=10)


def test_allowed_decision_has_zero_retry_after(clock: FakeClock) -> None:
    lim = SlidingWindowLimiter(_small(1), clock=clock)
    assert lim.hit("k") == RateDecision(allowed=True, retry_after=0)


def test_the_window_slides(clock: FakeClock) -> None:
    lim = SlidingWindowLimiter(_small(2, 10), clock=clock)
    lim.hit("k")
    clock.advance(5)
    lim.hit("k")
    assert not lim.hit("k").allowed
    clock.advance(5)  # the first hit is now exactly one window old
    assert lim.hit("k").allowed
    assert not lim.hit("k").allowed


def test_retry_after_counts_down_to_the_oldest_hit(clock: FakeClock) -> None:
    lim = SlidingWindowLimiter(_small(2, 60), clock=clock)
    lim.hit("k")
    clock.advance(20)
    lim.hit("k")
    assert lim.hit("k").retry_after == 40
    clock.advance(39.5)
    assert lim.peek("k") == RateDecision(allowed=False, retry_after=1)
    clock.advance(0.5)
    assert lim.peek("k").allowed


def test_refused_hits_are_not_recorded(clock: FakeClock) -> None:
    lim = SlidingWindowLimiter(_small(1, 10), clock=clock)
    lim.hit("k")
    for _ in range(5):
        clock.advance(1)
        assert not lim.hit("k").allowed
    clock.advance(5)  # 10 s after the only recorded hit
    assert lim.hit("k").allowed


def test_peek_does_not_record(clock: FakeClock) -> None:
    lim = SlidingWindowLimiter(_small(1), clock=clock)
    for _ in range(5):
        assert lim.peek("k").allowed
    assert lim.hit("k").allowed


def test_record_counts_without_deciding(clock: FakeClock) -> None:
    lim = SlidingWindowLimiter(_small(2), clock=clock)
    lim.record("k")
    lim.record("k")
    lim.record("k")  # beyond the limit: still bounded
    assert not lim.peek("k").allowed


def test_keys_are_independent(clock: FakeClock) -> None:
    lim = SlidingWindowLimiter(_small(1), clock=clock)
    assert lim.hit("a").allowed
    assert not lim.hit("a").allowed
    assert lim.hit("b").allowed


def test_memory_is_bounded(clock: FakeClock) -> None:
    lim = SlidingWindowLimiter(_small(1), clock=clock, max_keys=3)
    for key in ("a", "b", "c"):
        lim.hit(key)
    lim.hit("a")  # refused, but "a" becomes most recently used
    lim.hit("d")  # evicts the least recently used key: "b"
    assert len(lim) == 3
    assert lim.peek("b").allowed  # forgotten
    assert not lim.peek("a").allowed  # kept
    assert not lim.peek("c").allowed
    assert not lim.peek("d").allowed


def test_expired_keys_are_dropped(clock: FakeClock) -> None:
    lim = SlidingWindowLimiter(_small(1, 10), clock=clock)
    lim.hit("a")
    clock.advance(10)
    lim.peek("a")
    assert len(lim) == 0


def test_raw_tokens_are_never_stored_as_keys(clock: FakeClock) -> None:
    lim = SlidingWindowLimiter(_small(1), clock=clock)
    lim.hit(RAW_TOKEN)
    lim.record(RAW_TOKEN)
    stored = list(lim._hits)  # pyright: ignore[reportPrivateUsage]  # inspect storage
    assert stored
    assert all(RAW_TOKEN not in key and "s3cr3t" not in key for key in stored)
    assert "s3cr3t" not in repr(lim)
    assert not lim.hit(RAW_TOKEN).allowed  # still keyed consistently


def test_policy_rejects_nonsense() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        RateLimitPolicy("bad", 0, 60)
    with pytest.raises(ValueError, match="at least 1"):
        RateLimitPolicy("bad", 1, 0)
    with pytest.raises(ValueError, match="max_keys"):
        SlidingWindowLimiter(_small(), max_keys=0)


def test_policies_match_the_design() -> None:
    assert (MCP_CALLS.limit, MCP_CALLS.window_seconds) == (120, 60)
    assert (TOKEN.limit, TOKEN.window_seconds) == (30, 60)
    assert (AUTHORIZE.limit, AUTHORIZE.window_seconds) == (30, 60)
    assert (REGISTER.limit, REGISTER.window_seconds) == (10, 3600)
    assert (BEARER_FAILURES.limit, BEARER_FAILURES.window_seconds) == (20, 60)
    assert (CONSENT.limit, CONSENT.window_seconds) == (10, 60)
    assert (REVOKE.limit, REVOKE.window_seconds) == (30, 60)
    policies = (MCP_CALLS, TOKEN, AUTHORIZE, REGISTER, BEARER_FAILURES, CONSENT, REVOKE)
    assert len({p.name for p in policies}) == 7


def test_process_wide_limiter_is_one_per_policy(clock: FakeClock) -> None:
    assert limiter(TOKEN) is limiter(TOKEN)
    assert limiter(TOKEN) is not limiter(AUTHORIZE)
    first = limiter(TOKEN)
    reset_limiters(clock=clock)
    assert limiter(TOKEN) is not first


# --- responses and keys -----------------------------------------------------


def test_429_response_shape() -> None:
    response = too_many_requests(RateDecision(allowed=False, retry_after=7))
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "7"
    body = bytes(response.body).decode()
    assert '"error":"rate_limited"' in body
    assert "Try again in 7 seconds." in body
    assert "atl_" not in body


def test_source_key_uses_a_public_client_host() -> None:
    assert source_key({"type": "http", "client": ("8.8.4.4", 4321)}) == "8.8.4.4"
    assert source_key({"type": "http", "client": ("2606:4700::1", 1)}) == "2606:4700::1"


@pytest.mark.parametrize(
    "client",
    [
        ("172.18.0.5", 4321),  # the nginx container on the compose network
        ("10.0.0.5", 1),
        ("192.168.1.2", 1),
        ("127.0.0.1", 1),
        ("::1", 1),
        ("fd00::1", 1),
        ("fe80::1", 1),
        ("169.254.1.1", 1),
        ("::ffff:10.0.0.1", 1),
        ("not-an-ip", 1),
        (),
        None,
        "garbage",
    ],
)
def test_source_key_treats_proxies_and_malformed_peers_as_unknown(
    client: object,
) -> None:
    assert source_key({"type": "http", "client": client}) == "unknown"
    assert source_key({"type": "http"}) == "unknown"


# --- ASGI wrappers ----------------------------------------------------------


async def test_rate_limited_endpoint_wraps_an_asgi_route(clock: FakeClock) -> None:
    app = RateLimitedEndpoint(_status_app, _small(2, 30))
    async with _client(app) as client:
        assert (await client.get("/ok")).status_code == 200
        assert (await client.get("/ok")).status_code == 200
        refused = await client.get("/ok")
        assert refused.status_code == 429
        assert refused.headers["Retry-After"] == "30"
        clock.advance(30)
        assert (await client.get("/ok")).status_code == 200


async def test_rate_limited_endpoint_uses_a_custom_key(clock: FakeClock) -> None:
    def by_path(scope: Scope) -> str:
        return str(scope["path"])

    app = RateLimitedEndpoint(_status_app, _small(1), key=by_path)
    async with _client(app) as client:
        assert (await client.get("/a")).status_code == 200
        assert (await client.get("/b")).status_code == 200
        assert (await client.get("/a")).status_code == 429


async def test_failed_bearer_guard_blocks_after_20_failures_and_recovers(
    clock: FakeClock,
) -> None:
    app = FailedBearerGuard(_status_app)
    headers = {"Authorization": f"Bearer {RAW_TOKEN}"}
    async with _client(app) as client:
        for _ in range(20):
            assert (await client.get("/deny", headers=headers)).status_code == 401
        blocked = await client.get("/ok", headers=headers)
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) == 60
        assert "s3cr3t" not in blocked.text
        clock.advance(60)
        assert (await client.get("/ok", headers=headers)).status_code == 200


async def test_failed_bearer_guard_ignores_requests_without_a_bearer_and_successes(
    clock: FakeClock,
) -> None:
    app = FailedBearerGuard(_status_app, _small(2))
    bearer = {"Authorization": "Bearer whatever"}
    async with _client(app) as client:
        for _ in range(10):
            assert (await client.get("/deny")).status_code == 401
            assert (await client.get("/ok", headers=bearer)).status_code == 200
            basic = {"Authorization": "Basic Zm9vOmJhcg=="}
            assert (await client.get("/deny", headers=basic)).status_code == 401
        assert (await client.get("/deny", headers=bearer)).status_code == 401
        assert (await client.get("/deny", headers=bearer)).status_code == 401
        assert (await client.get("/ok", headers=bearer)).status_code == 429
        # Requests without a bearer are still served while the source is blocked.
        assert (await client.get("/ok")).status_code == 200


async def test_principal_rate_limit_keys_by_principal_and_skips_anonymous(
    clock: FakeClock,
) -> None:
    def principal(scope: Scope) -> str | None:
        for name, value in scope["headers"]:
            if name == b"x-token-id":
                return value.decode()
        return None

    app = PrincipalRateLimit(_status_app, _small(1), key=principal)
    t1, t2 = {"x-token-id": "t1"}, {"x-token-id": "t2"}
    async with _client(app) as client:
        assert (await client.get("/ok", headers=t1)).status_code == 200
        assert (await client.get("/ok", headers=t1)).status_code == 429
        assert (await client.get("/ok", headers=t2)).status_code == 200
        for _ in range(3):
            assert (await client.get("/ok")).status_code == 200


async def test_wrappers_pass_non_http_scopes_through(clock: FakeClock) -> None:
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    async def receive() -> dict[str, object]:
        return {}

    async def send(message: object) -> None:
        return None

    policy = _small(1)
    for wrapper in (
        RateLimitedEndpoint(inner, policy),
        FailedBearerGuard(inner, policy),
        PrincipalRateLimit(inner, policy, key=lambda _s: "k"),
    ):
        for _ in range(3):
            await wrapper({"type": "lifespan"}, receive, send)  # type: ignore[arg-type]  # minimal ASGI stubs
    assert seen == ["lifespan"] * 9


# --- FastAPI dependency -----------------------------------------------------


async def test_fastapi_dependency_raises_429_with_retry_after(clock: FakeClock) -> None:
    async def by_user(request: Request) -> str:
        return request.headers.get("x-user", "anon")

    api = FastAPI()

    @api.post("/consent", dependencies=[Depends(rate_limit(_small(1, 60), by_user))])
    async def consent() -> Response:  # pyright: ignore[reportUnusedFunction]  # registered by decorator
        return JSONResponse({"ok": True})

    u1, u2 = {"x-user": "u1"}, {"x-user": "u2"}
    async with _client(api) as client:
        assert (await client.post("/consent", headers=u1)).status_code == 200
        refused = await client.post("/consent", headers=u1)
        assert refused.status_code == 429
        assert refused.headers["Retry-After"] == "60"
        assert refused.json()["detail"]["error"] == "rate_limited"
        assert "u1" not in refused.text
        assert (await client.post("/consent", headers=u2)).status_code == 200


# --- Task 6: E1, policy-keyed registry, streaming ---------------------------


def test_policies_sharing_a_name_never_share_a_budget(clock: FakeClock) -> None:
    tight, loose = RateLimitPolicy("same", 1, 60), RateLimitPolicy("same", 5, 60)
    assert limiter(tight) is not limiter(loose)
    assert limiter(tight).hit("k").allowed
    assert not limiter(tight).hit("k").allowed
    assert limiter(loose).hit("k").allowed


async def test_failed_bearer_guard_counts_only_what_counts_says(
    clock: FakeClock,
) -> None:
    unrecognised = [False]
    app = FailedBearerGuard(_status_app, _small(2), counts=lambda: unrecognised[0])
    bearer = {"Authorization": f"Bearer {RAW_TOKEN}"}
    async with _client(app) as client:
        for _ in range(5):  # e.g. expired tokens: refused, never counted
            assert (await client.get("/deny", headers=bearer)).status_code == 401
        assert (await client.get("/ok", headers=bearer)).status_code == 200
        unrecognised[0] = True
        for _ in range(2):
            assert (await client.get("/deny", headers=bearer)).status_code == 401
        assert (await client.get("/ok", headers=bearer)).status_code == 429


async def test_failed_bearer_guard_never_blocks_an_unknown_source(
    clock: FakeClock,
) -> None:
    calls: list[int] = []

    async def deny(scope: Scope, receive: Receive, send: Send) -> None:
        calls.append(1)
        await PlainTextResponse("x", status_code=401)(scope, receive, send)

    app = FailedBearerGuard(deny, _small(1))
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/deny",
        "headers": [(b"authorization", f"Bearer {RAW_TOKEN}".encode())],
        "query_string": b"",
        "client": None,
    }
    with capture_logs() as logs:
        for _ in range(5):
            await app(scope, receive, send)  # type: ignore[arg-type]  # minimal ASGI stubs
    statuses = [m["status"] for m in sent if m["type"] == "http.response.start"]
    assert statuses == [401] * 5
    assert len(calls) == 5
    assert len(limiter(_small(1))) == 0
    unattributed = [
        e for e in logs if e["event"] == "ratelimit.bearer_failure_unattributed"
    ]
    assert len(unattributed) == 5
    assert RAW_TOKEN not in str(logs)


async def test_wrappers_pass_multi_chunk_streams_through(clock: FakeClock) -> None:
    async def stream(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        for chunk in (b"data: one\n\n", b"data: two\n\n", b"data: three\n\n"):
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    policy = _small(100)
    bearer = {"Authorization": "Bearer whatever", "x-token-id": "t1"}
    for wrapper in (
        RateLimitedEndpoint(stream, policy),
        FailedBearerGuard(stream, policy),
        PrincipalRateLimit(stream, policy, key=lambda _s: "k"),
    ):
        async with (
            _client(wrapper) as client,
            client.stream("GET", "/sse", headers=bearer) as response,
        ):
            chunks = [c async for c in response.aiter_bytes()]
        assert response.status_code == 200
        assert b"".join(chunks) == b"data: one\n\ndata: two\n\ndata: three\n\n"


async def test_fastapi_dependency_key_may_depend_on_other_dependencies(
    clock: FakeClock,
) -> None:
    async def caller(request: Request) -> str:
        return request.headers.get("x-user", "anon")

    async def by_caller(user: str = Depends(caller)) -> str:
        return f"user:{user}"

    api = FastAPI()

    @api.get("/c", dependencies=[Depends(rate_limit(_small(1, 60), by_caller))])
    async def c() -> Response:  # pyright: ignore[reportUnusedFunction]  # registered by decorator
        return JSONResponse({"ok": True})

    async with _client(api) as client:
        assert (await client.get("/c", headers={"x-user": "u1"})).status_code == 200
        assert (await client.get("/c", headers={"x-user": "u1"})).status_code == 429
        assert (await client.get("/c", headers={"x-user": "u2"})).status_code == 200


async def test_failed_bearer_guard_never_blocks_a_private_peer(
    clock: FakeClock,
) -> None:
    app = FailedBearerGuard(_status_app)
    headers = {"Authorization": f"Bearer {RAW_TOKEN}"}
    async with _client(app, peer="172.18.0.5") as client:
        for _ in range(25):
            assert (await client.get("/deny", headers=headers)).status_code == 401
        assert (await client.get("/ok", headers=headers)).status_code == 200


async def test_failed_bearer_guard_blocks_a_public_peer_after_20(
    clock: FakeClock,
) -> None:
    app = FailedBearerGuard(_status_app)
    headers = {"Authorization": f"Bearer {RAW_TOKEN}"}
    async with _client(app, peer="8.8.4.4") as client:
        for _ in range(20):
            assert (await client.get("/deny", headers=headers)).status_code == 401
        assert (await client.get("/deny", headers=headers)).status_code == 429
    async with _client(app, peer="2606:4700::1") as other:
        assert (await other.get("/ok", headers=headers)).status_code == 200
