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
import ipaddress
import math
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

import structlog
from fastapi import Depends, HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger()

Clock = Callable[[], float]
UNKNOWN_SOURCE = "unknown"


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
REVOKE = RateLimitPolicy("oauth_revoke", 30, 60)


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
    """Process-wide limiters, one per policy, sharing one clock."""

    def __init__(self) -> None:
        self.clock: Clock = time.monotonic
        self.limiters: dict[RateLimitPolicy, SlidingWindowLimiter] = {}


_registry = _Registry()


def limiter(policy: RateLimitPolicy) -> SlidingWindowLimiter:
    """The process-wide limiter for ``policy``. Keyed by the whole frozen policy, so
    two policies that share a name never share (or misreport) a budget."""
    found = _registry.limiters.get(policy)
    if found is None:
        found = SlidingWindowLimiter(policy, clock=_registry.clock)
        _registry.limiters[policy] = found
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
    """The ASGI client's public IP, or ``"unknown"``.

    A loopback, private (RFC 1918, IPv6 ULA), link-local or unparsable peer is
    ``"unknown"``: in 4a every caller arrives through nginx or the SSH tunnel, so
    such a peer is our own proxy and says nothing about who is calling (C15, ruling
    E1). Per-source limits are then global, and the failed-bearer guard only logs.
    A public IP (4b, via trusted proxy headers) is keyed as itself.
    """
    client: object = scope.get("client")
    if not isinstance(client, (tuple, list)) or not client:
        return UNKNOWN_SOURCE
    host = str(cast(tuple[object, ...], client)[0])
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return UNKNOWN_SOURCE
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_private or address.is_loopback or address.is_link_local:
        return UNKNOWN_SOURCE
    return host


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


def _always() -> bool:
    return True


class FailedBearerGuard:
    """Blocks a source after too many 401s on requests that carried a bearer.

    Requests without a bearer are never counted, so the first 401 of the OAuth
    handshake is free; successful bearers are never counted either. ``counts`` is
    asked when a 401 starts whether this failure is evidence of guessing (ruling E1:
    only unrecognised bearers, never a real token that expired); it runs in the
    request's own task, inside the authentication that decided the 401.

    A source of ``"unknown"`` is never blocked (E1): behind a proxy without trusted
    client addresses every caller shares that key (C15), so blocking it would lock
    everyone out. Its failures are logged instead. Guessing a 256-bit token is moot.
    """

    def __init__(
        self,
        app: ASGIApp,
        policy: RateLimitPolicy = BEARER_FAILURES,
        *,
        counts: Callable[[], bool] = _always,
    ) -> None:
        self._app = app
        self._policy = policy
        self._counts = counts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _has_bearer(scope):
            await self._app(scope, receive, send)
            return
        source = source_key(scope)
        if source != UNKNOWN_SOURCE:
            decision = limiter(self._policy).peek(source)
            if not decision.allowed:
                await too_many_requests(decision)(scope, receive, send)
                return

        async def watch(message: Message) -> None:
            if (
                message["type"] == "http.response.start"
                and message["status"] == 401
                and self._counts()
            ):
                self._failed(source)
            await send(message)

        await self._app(scope, receive, watch)

    def _failed(self, source: str) -> None:
        if source == UNKNOWN_SOURCE:
            logger.info(
                "ratelimit.bearer_failure_unattributed", policy=self._policy.name
            )
            return
        limiter(self._policy).record(source)


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
    key: Callable[..., Awaitable[str]],
) -> Callable[..., Awaitable[None]]:
    """A FastAPI dependency that raises 429 with ``Retry-After`` when over the limit.

    ``key`` is itself a dependency (it may take the ``Request`` or depend on the
    caller's principal), resolved once per request by FastAPI."""

    async def dependency(value: str = Depends(key)) -> None:
        decision = limiter(policy).hit(value)
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail=_message(decision),
                headers=_headers(decision),
            )

    return dependency
