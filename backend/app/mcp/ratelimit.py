"""In-process sliding-window rate limits for the MCP and OAuth surfaces (D16).

One uvicorn worker serves the app, so a per-process limiter is exact. Every limiter
keeps at most ``max_keys`` keys (LRU eviction) and at most ``policy.limit`` hit times
per key, so memory is bounded whatever callers send. Keys are stored only as SHA-256
digests: a caller that passes a raw token by mistake still never holds it in memory
longer than the call. Refusals are 429 with ``Retry-After`` and a body that never
echoes the key.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    name: str
    limit: int
    window_seconds: int

    def __post_init__(self) -> None:
        if self.limit < 1 or self.window_seconds < 1:
            raise ValueError("rate limit and window must be at least 1")


MCP_CALLS = RateLimitPolicy("mcp_calls", 120, 60)
TOKEN = RateLimitPolicy("oauth_token", 30, 60)
AUTHORIZE = RateLimitPolicy("oauth_authorize", 30, 60)
REGISTER = RateLimitPolicy("oauth_register", 10, 3600)
BEARER_FAILURES = RateLimitPolicy("bearer_failures", 20, 60)
CONSENT = RateLimitPolicy("oauth_consent", 10, 60)


@dataclass(frozen=True, slots=True)
class RateDecision:
    allowed: bool
    retry_after: int  # whole seconds, >= 1 when refused, 0 when allowed


_ALLOWED = RateDecision(allowed=True, retry_after=0)


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class SlidingWindowLimiter:
    """Counts hits per key over a sliding window. Synchronous, so atomic on one loop."""

    def __init__(
        self,
        policy: RateLimitPolicy,
        clock: Clock = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        if max_keys < 1:
            raise ValueError("max_keys must be at least 1")
        self._policy = policy
        self._clock = clock
        self._max_keys = max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._hits)

    def __repr__(self) -> str:
        return f"SlidingWindowLimiter(policy={self._policy.name!r}, keys={len(self)})"

    def hit(self, key: str) -> RateDecision:
        """Record a hit and decide. A refused hit is not recorded."""
        digest, now = _digest(key), self._clock()
        decision = self._decide(digest, now)
        if decision.allowed:
            self._append(digest, now)
        return decision

    def peek(self, key: str) -> RateDecision:
        """Decide without recording."""
        return self._decide(_digest(key), self._clock())

    def record(self, key: str) -> None:
        """Record without deciding (for example a failed bearer attempt)."""
        self._append(_digest(key), self._clock())

    def _decide(self, digest: str, now: float) -> RateDecision:
        hits = self._live(digest, now)
        if hits is None or len(hits) < self._policy.limit:
            return _ALLOWED
        wait = math.ceil(hits[0] + self._policy.window_seconds - now)
        return RateDecision(allowed=False, retry_after=max(1, wait))

    def _live(self, digest: str, now: float) -> deque[float] | None:
        hits = self._hits.get(digest)
        if hits is None:
            return None
        cutoff = now - self._policy.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if not hits:
            del self._hits[digest]
            return None
        self._hits.move_to_end(digest)
        return hits

    def _append(self, digest: str, now: float) -> None:
        hits = self._live(digest, now)
        if hits is None:
            hits = deque[float](maxlen=self._policy.limit)
            self._hits[digest] = hits
            while len(self._hits) > self._max_keys:
                self._hits.popitem(last=False)
        hits.append(now)


# --- process-wide limiters ----------------------------------------------------


class _Registry:
    """Process-wide limiters, one per policy name, sharing one clock."""

    def __init__(self) -> None:
        self.clock: Clock = time.monotonic
        self.limiters: dict[str, SlidingWindowLimiter] = {}


_registry = _Registry()


def limiter(policy: RateLimitPolicy) -> SlidingWindowLimiter:
    """The process-wide limiter for ``policy`` (one per policy name)."""
    found = _registry.limiters.get(policy.name)
    if found is None:
        found = SlidingWindowLimiter(policy, clock=_registry.clock)
        _registry.limiters[policy.name] = found
    return found


def reset_limiters(clock: Clock = time.monotonic) -> None:
    """Forget every process-wide limiter; new ones use ``clock`` (tests)."""
    _registry.limiters.clear()
    _registry.clock = clock


# --- responses and keys -------------------------------------------------------


def _message(decision: RateDecision) -> dict[str, str]:
    return {
        "error": "rate_limited",
        "error_description": (
            f"Too many requests. Try again in {decision.retry_after} seconds."
        ),
    }


def _headers(decision: RateDecision) -> dict[str, str]:
    return {"Retry-After": str(decision.retry_after)}


def too_many_requests(decision: RateDecision) -> JSONResponse:
    """A 429 with ``Retry-After``; the body never echoes the key."""
    return JSONResponse(_message(decision), status_code=429, headers=_headers(decision))


def source_key(scope: Scope) -> str:
    """The ASGI client host, or ``"unknown"`` (global behind a proxy, C15)."""
    client = scope.get("client")
    if not client:
        return "unknown"
    return str(client[0])


def _has_bearer(scope: Scope) -> bool:
    for name, value in scope.get("headers", ()):
        if name.lower() == b"authorization":
            return value[:7].lower() == b"bearer "
    return False


# --- ASGI wrappers --------------------------------------------------------------


class RateLimitedEndpoint:
    """Wraps one ASGI route endpoint; every HTTP request counts against ``key``."""

    def __init__(
        self,
        app: ASGIApp,
        policy: RateLimitPolicy,
        key: Callable[[Scope], str] = source_key,
    ) -> None:
        self._app = app
        self._policy = policy
        self._key = key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            decision = limiter(self._policy).hit(self._key(scope))
            if not decision.allowed:
                await too_many_requests(decision)(scope, receive, send)
                return
        await self._app(scope, receive, send)


class FailedBearerGuard:
    """Blocks a source after too many 401s on requests that carried a bearer.

    Requests without a bearer are never counted, so the first 401 of the OAuth
    handshake is free; successful bearers are never counted either.
    """

    def __init__(self, app: ASGIApp, policy: RateLimitPolicy = BEARER_FAILURES) -> None:
        self._app = app
        self._policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _has_bearer(scope):
            await self._app(scope, receive, send)
            return
        source = source_key(scope)
        decision = limiter(self._policy).peek(source)
        if not decision.allowed:
            await too_many_requests(decision)(scope, receive, send)
            return

        async def watch(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] == 401:
                limiter(self._policy).record(source)
            await send(message)

        await self._app(scope, receive, watch)


class PrincipalRateLimit:
    """Limits authenticated callers by ``key(scope)``; ``None`` (anonymous) skips."""

    def __init__(
        self,
        app: ASGIApp,
        policy: RateLimitPolicy,
        key: Callable[[Scope], str | None],
    ) -> None:
        self._app = app
        self._policy = policy
        self._key = key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            principal = self._key(scope)
            if principal is not None:
                decision = limiter(self._policy).hit(principal)
                if not decision.allowed:
                    await too_many_requests(decision)(scope, receive, send)
                    return
        await self._app(scope, receive, send)


# --- FastAPI dependency ---------------------------------------------------------


def rate_limit(
    policy: RateLimitPolicy,
    key: Callable[[Request], Awaitable[str]],
) -> Callable[..., Awaitable[None]]:
    """A FastAPI dependency that raises 429 with ``Retry-After`` when over the limit."""

    async def dependency(request: Request) -> None:
        decision = limiter(policy).hit(await key(request))
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail=_message(decision),
                headers=_headers(decision),
            )

    return dependency
