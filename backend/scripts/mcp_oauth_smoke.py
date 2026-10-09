"""End-to-end smoke test of the MCP OAuth door against a running atlas.

Drives what Claude Code does, with real PKCE (S256), and prints one PASS/FAIL line
per check; it stops with exit code 1 at the first failure. Tokens are printed only
as display prefixes, never in full.

  1. discovery: 401 + WWW-Authenticate -> protected-resource metadata -> AS metadata
     (RFC 8414 path insertion); every OAuth endpoint is taken from the metadata and
     must live under --base-url
  2. dynamic client registration (public client, loopback redirect)
  3. /authorize -> 302 to /oauth/consent?txn=
  4. consent prompt + approve (POST /api/v1/oauth/consent)
  5. redirect carries the code and the same state
  6. /token: code + verifier -> access + refresh
  7. MCP initialize, tools/list, tools/call list_metrics
  8. refresh rotation; old refresh replayed after the 30 s grace -> invalid_grant,
     and the whole family is dead (the newest access token -> 401)
  9. fresh flow, /revoke -> the access token -> 401
 10. fresh flow, code replay -> invalid_grant and the family is dead
 11. PAT from ATLAS_PAT: tools/list with the PAT
     11b. optional, a revoked PAT from ATLAS_REVOKED_PAT: initialize and tools/list
          -> 401
 12. optional (--check-register-limit --allow-shared-impact): /register until 429
     + Retry-After

Secrets come only from the environment, never from flags (other local users can see
a process's arguments): ATLAS_FIREBASE_TOKEN (consent bearer), ATLAS_PAT and
ATLAS_REVOKED_PAT (mint and revoke them with `python -m app.mcp.cli` or the atlas UI
beforehand, so the script also runs against the public URL).

Consent: under AUTH_DISABLED (development) no bearer is needed; otherwise set
ATLAS_FIREBASE_TOKEN to a Firebase ID token of the consenting user.

`--expect-ineligible` checks a user without mcp:use instead: the consent prompt says
ineligible, approval is refused with 403 `no_mcp_use`, and (with a PAT minted while
the user still had access) tools/list is empty and tools/call is denied.

A plain-http --base-url is accepted only for a loopback host (a bearer never crosses
the network in clear). --base-url must equal the server's ATLAS_PUBLIC_URL, because
every advertised URL is built from it. Run from backend/ against the local stack:
  uv run python scripts/mcp_oauth_smoke.py --base-url http://localhost:8080

A normal run registers 3 clients and --expect-ineligible 1. In 4a the /register
budget (10 per hour) is shared by every caller behind nginx or the tunnel, so keep
repeated runs against a shared deployment to a minimum.
"""

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

import httpx

_MCP_PATH = "/mcp-server/mcp"
_CONSENT_API = "/api/v1/oauth/consent"
_AS_WELL_KNOWN = "/.well-known/oauth-authorization-server"
_PROTOCOL_VERSION = "2025-06-18"
_INITIALIZE_PARAMS: Mapping[str, object] = {
    "protocolVersion": _PROTOCOL_VERSION,
    "capabilities": {},
    "clientInfo": {"name": "atlas-smoke", "version": "1"},
}
_EXPECTED_TOOLS = frozenset(
    {
        "list_metrics",
        "search_atlas",
        "describe_entity",
        "query_metric",
        "metric_breakdown",
        "compare_periods",
        "funnel_analyze",
    }
)
_GRACE_WAIT_SECONDS = 31
_REGISTER_ATTEMPTS = 12
_FIREBASE_ENV = "ATLAS_FIREBASE_TOKEN"
_PAT_ENV = "ATLAS_PAT"
_REVOKED_PAT_ENV = "ATLAS_REVOKED_PAT"
_ATLAS_TOKEN = re.compile(r"atl_[a-z]{3}_")
_ATLAS_PREFIX_LENGTH = 14
_OTHER_PREFIX_LENGTH = 6


class _CheckFailedError(Exception):
    """A smoke check did not hold; the message never contains a raw secret."""


def _shown(secret: str) -> str:
    """What may be printed of a secret: its display prefix.

    Deliberately mirrors `app.identity`'s display_prefix instead of importing it, so
    the script stays independent of `app/` (it only needs httpx and the stdlib).
    """
    if _ATLAS_TOKEN.match(secret):
        return secret[:_ATLAS_PREFIX_LENGTH] + "..."
    return secret[:_OTHER_PREFIX_LENGTH] + "..."


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise _CheckFailedError(message)


def _passed(step: str, detail: str = "") -> None:
    print(f"PASS {step}" + (f" ({detail})" if detail else ""), flush=True)


def _pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge) per RFC 7636."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def _query_param(url: str, name: str) -> str | None:
    values = parse_qs(urlsplit(url).query).get(name)
    return values[0] if values else None


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _base_url_problem(raw: str) -> str | None:
    """Why `raw` is not an acceptable --base-url, or None when it is."""
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return "--base-url must be an absolute http(s) URL"
    if parts.query or parts.fragment:
        return "--base-url must not carry a query or fragment"
    if parts.scheme == "http" and not _is_loopback(parts.hostname):
        return (
            "--base-url uses plain http for a non-loopback host; "
            "use https (a bearer is never sent in clear)"
        )
    return None


def _under(base: str, url: str) -> bool:
    return url == base or url.startswith(base + "/")


# ---- JSON narrowing (malformed answers become FAIL lines, not tracebacks) ----------


def _json_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _json_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _body_of(response: httpx.Response) -> dict[str, object]:
    try:
        parsed: object = response.json()
    except ValueError:
        return {}
    return _json_object(parsed)


def _error_of(response: httpx.Response) -> str:
    error = _text(_body_of(response).get("error"))
    return error if error is not None else f"HTTP {response.status_code}"


def _rpc_message(response: httpx.Response) -> dict[str, object]:
    """The JSON-RPC message from a streamable-HTTP answer (SSE or JSON)."""
    text = response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        data = [
            line[5:].strip() for line in text.splitlines() if line.startswith("data:")
        ]
        _expect(bool(data), "MCP answer has no SSE data line")
        text = data[-1]
    try:
        parsed: object = json.loads(text)
    except ValueError as exc:
        raise _CheckFailedError("MCP answer is not JSON") from exc
    _expect(isinstance(parsed, dict), "MCP answer is not a JSON-RPC object")
    return _json_object(parsed)


def _mcp_request(
    http: httpx.Client,
    url: str,
    token: str | None,
    method: str,
    params: Mapping[str, object] | None = None,
) -> httpx.Response:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": _PROTOCOL_VERSION,
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return http.post(url, json=body, headers=headers)


# ---- discovery -------------------------------------------------------------------


@dataclass(frozen=True)
class _Endpoints:
    registration: str
    authorization: str
    token: str
    revocation: str


def _as_metadata_url(issuer: str) -> str:
    """RFC 8414 §3.1: the well-known segment goes between the origin and the path."""
    parts = urlsplit(issuer)
    path = parts.path.rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{_AS_WELL_KNOWN}{path}"


def _advertised(base: str, value: object, what: str) -> str:
    """An advertised URL, which must live under --base-url."""
    url = _text(value)
    _expect(bool(url), f"{what}: not advertised")
    advertised = str(url)
    _expect(
        _under(base, advertised),
        f"{what} {advertised} is not under --base-url {base}",
    )
    return advertised


def _get_json(http: httpx.Client, url: str, what: str) -> dict[str, object]:
    response = http.get(url)
    _expect(
        response.status_code == HTTPStatus.OK,
        f"{what}: HTTP {response.status_code}",
    )
    body = _body_of(response)
    _expect(bool(body), f"{what}: not a JSON object")
    return body


def _discover(http: httpx.Client, base: str) -> _Endpoints:
    """Step 1, as a client does it: nothing but the MCP URL is assumed."""
    response = _mcp_request(http, f"{base}{_MCP_PATH}", None, "tools/list")
    _expect(
        response.status_code == HTTPStatus.UNAUTHORIZED,
        f"no bearer: expected 401, got {response.status_code}",
    )
    challenge = response.headers.get("www-authenticate", "")
    _expect(
        challenge.lower().startswith("bearer "),
        "401 challenge is not a Bearer challenge",
    )
    match = re.search(
        r'(?:^|[\s,])resource_metadata=(?:"([^"]*)"|([^\s,]+))', challenge
    )
    _expect(match is not None, "401 has no resource_metadata in WWW-Authenticate")
    prm_raw = (match.group(1) or match.group(2)) if match else None
    prm_url = _advertised(base, prm_raw, "resource_metadata")
    prm = _get_json(http, prm_url, "protected-resource metadata")
    resource = _advertised(base, prm.get("resource"), "PRM resource")
    _expect(
        resource == f"{base}{_MCP_PATH}",
        f"PRM resource {resource} is not {base}{_MCP_PATH}",
    )
    servers = _json_list(prm.get("authorization_servers"))
    _expect(bool(servers), "PRM lists no authorization server")
    issuer = _advertised(base, servers[0], "authorization server")
    meta = _get_json(http, _as_metadata_url(issuer), "AS metadata")
    _expect(_text(meta.get("issuer")) == issuer, "AS metadata issuer mismatch")
    _expect(
        "S256" in _json_list(meta.get("code_challenge_methods_supported")),
        "AS metadata does not advertise S256",
    )
    _expect(
        "none" in _json_list(meta.get("token_endpoint_auth_methods_supported")),
        "AS metadata does not advertise public clients (none)",
    )
    endpoints = _Endpoints(
        registration=_advertised(
            base, meta.get("registration_endpoint"), "registration_endpoint"
        ),
        authorization=_advertised(
            base, meta.get("authorization_endpoint"), "authorization_endpoint"
        ),
        token=_advertised(base, meta.get("token_endpoint"), "token_endpoint"),
        revocation=_advertised(
            base, meta.get("revocation_endpoint"), "revocation_endpoint"
        ),
    )
    _passed("1 discovery", "401 challenge, PRM, AS metadata (S256, none, endpoints)")
    return endpoints


# ---- the flow --------------------------------------------------------------------


@dataclass(frozen=True)
class _Client:
    client_id: str
    redirect_uri: str


@dataclass(frozen=True)
class _Tokens:
    access: str
    refresh: str


class _Smoke:
    def __init__(
        self,
        http: httpx.Client,
        base: str,
        endpoints: _Endpoints,
        firebase: str | None,
    ) -> None:
        self.http = http
        self.base = base
        self.endpoints = endpoints
        self.resource = f"{base}{_MCP_PATH}"
        self.consent_headers = (
            {"Authorization": f"Bearer {firebase}"} if firebase else {}
        )

    # ---- protocol pieces ---------------------------------------------------------

    def mcp(
        self,
        token: str | None,
        method: str,
        params: Mapping[str, object] | None = None,
    ) -> httpx.Response:
        return _mcp_request(self.http, self.resource, token, method, params)

    def rpc(
        self, token: str, method: str, params: Mapping[str, object] | None = None
    ) -> dict[str, object]:
        response = self.mcp(token, method, params)
        _expect(
            response.status_code == HTTPStatus.OK,
            f"{method}: HTTP {response.status_code}",
        )
        message = _rpc_message(response)
        error = _json_object(message.get("error"))
        _expect("error" not in message, f"{method}: JSON-RPC error {error.get('code')}")
        result = message.get("result")
        _expect(isinstance(result, dict), f"{method}: no result object")
        return _json_object(result)

    def tool_names(self, token: str) -> set[str]:
        names: set[str] = set()
        for tool in _json_list(self.rpc(token, "tools/list").get("tools")):
            name = _text(_json_object(tool).get("name"))
            _expect(name is not None, "tools/list: a tool without a name")
            names.add(str(name))
        return names

    def call_list_metrics(self, token: str) -> dict[str, object]:
        result = self.rpc(
            token, "tools/call", {"name": "list_metrics", "arguments": {}}
        )
        content = _json_list(result.get("content"))
        _expect(bool(content), "list_metrics: no content")
        text = _text(_json_object(content[0]).get("text"))
        _expect(text is not None, "list_metrics: first content item has no text")
        try:
            parsed: object = json.loads(str(text))
        except ValueError as exc:
            raise _CheckFailedError("list_metrics: text is not JSON") from exc
        _expect(isinstance(parsed, dict), "list_metrics did not return an object")
        return _json_object(parsed)

    def expect_mcp_401(
        self,
        token: str,
        step: str,
        method: str = "tools/list",
        params: Mapping[str, object] | None = None,
    ) -> None:
        status = self.mcp(token, method, params).status_code
        _expect(
            status == HTTPStatus.UNAUTHORIZED,
            f"{step}: {method} expected 401, got {status}",
        )

    def register_request(self, client_name: str, redirect: str) -> httpx.Response:
        return self.http.post(
            self.endpoints.registration,
            json={
                "client_name": client_name,
                "redirect_uris": [redirect],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )

    def register(self) -> _Client:
        redirect = f"http://localhost:{_free_port()}/callback"
        response = self.register_request("atlas smoke", redirect)
        _expect(
            response.status_code == HTTPStatus.CREATED,
            f"register: HTTP {response.status_code} {_error_of(response)}",
        )
        body = _body_of(response)
        _expect("client_secret" not in body, "a public client got a client_secret")
        client_id = _text(body.get("client_id"))
        _expect(bool(client_id), "register: no client_id")
        return _Client(str(client_id), redirect)

    def authorize(self, client: _Client, challenge: str, state: str) -> str:
        """Runs /authorize; returns the consent transaction id."""
        response = self.http.get(
            self.endpoints.authorization,
            params={
                "response_type": "code",
                "client_id": client.client_id,
                "redirect_uri": client.redirect_uri,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
                "resource": self.resource,
            },
        )
        _expect(
            response.status_code == HTTPStatus.FOUND,
            f"authorize: expected 302, got {response.status_code}",
        )
        location = response.headers.get("location", "")
        _expect(
            location.startswith(f"{self.base}/oauth/consent?txn="),
            f"authorize: redirect is not the consent page ({urlsplit(location).path})",
        )
        txn = _query_param(location, "txn")
        _expect(txn is not None, "authorize: no txn in the consent redirect")
        return str(txn)

    def consent_prompt(self, txn: str) -> dict[str, object]:
        response = self.http.get(
            f"{self.base}{_CONSENT_API}/{txn}", headers=self.consent_headers
        )
        _expect(
            response.status_code == HTTPStatus.OK,
            f"consent prompt: HTTP {response.status_code}",
        )
        return _body_of(response)

    def decide(self, txn: str) -> httpx.Response:
        return self.http.post(
            f"{self.base}{_CONSENT_API}",
            json={"transaction_id": txn, "decision": "approve"},
            headers=self.consent_headers,
        )

    def exchange(self, client: _Client, code: str, verifier: str) -> httpx.Response:
        return self.http.post(
            self.endpoints.token,
            data={
                "grant_type": "authorization_code",
                "client_id": client.client_id,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": client.redirect_uri,
            },
        )

    def refresh(self, client: _Client, refresh_token: str) -> httpx.Response:
        return self.http.post(
            self.endpoints.token,
            data={
                "grant_type": "refresh_token",
                "client_id": client.client_id,
                "refresh_token": refresh_token,
            },
        )

    # ---- the steps ---------------------------------------------------------------

    def code_for(self, client: _Client, challenge: str, *, announce: bool) -> str:
        """authorize -> consent -> redirect; returns the code (state checked)."""
        state = secrets.token_urlsafe(16)
        txn = self.authorize(client, challenge, state)
        if announce:
            _passed("3 authorize", "302 to /oauth/consent?txn=")
        prompt = self.consent_prompt(txn)
        _expect(prompt.get("eligible") is True, "consent: the user is not eligible")
        _expect(
            prompt.get("loopback") is True, "consent: redirect not flagged loopback"
        )
        response = self.decide(txn)
        _expect(
            response.status_code == HTTPStatus.OK,
            f"consent approve: HTTP {response.status_code}",
        )
        redirect = _text(_body_of(response).get("redirect_to")) or ""
        if announce:
            _passed("4 consent", f"approved as {_text(prompt.get('user_email'))}")
        _expect(
            redirect.startswith(client.redirect_uri),
            "consent: redirect_to is not the registered redirect",
        )
        code = _query_param(redirect, "code")
        _expect(code is not None, "redirect: no code")
        _expect(_query_param(redirect, "state") == state, "redirect: state mismatch")
        if announce:
            _passed("5 redirect", f"code {_shown(str(code))}, state matches")
        return str(code)

    def tokens_from(self, response: httpx.Response, step: str) -> _Tokens:
        _expect(
            response.status_code == HTTPStatus.OK,
            f"{step}: HTTP {response.status_code} {_error_of(response)}",
        )
        body = _body_of(response)
        token_type = _text(body.get("token_type")) or ""
        _expect(token_type.lower() == "bearer", f"{step}: not bearer")
        access = _text(body.get("access_token"))
        refresh = _text(body.get("refresh_token"))
        _expect(bool(access), f"{step}: no access_token")
        _expect(bool(refresh), f"{step}: no refresh_token")
        return _Tokens(str(access), str(refresh))

    def login(self, *, announce: bool = False) -> tuple[_Client, _Tokens]:
        client = self.register()
        if announce:
            _passed("2 register", f"public client {_shown(client.client_id)}")
        verifier, challenge = _pkce_pair()
        code = self.code_for(client, challenge, announce=announce)
        tokens = self.tokens_from(self.exchange(client, code, verifier), "token")
        if announce:
            _passed(
                "6 token",
                f"access {_shown(tokens.access)}, refresh {_shown(tokens.refresh)}",
            )
        return client, tokens

    def mcp_calls(self, tokens: _Tokens) -> None:
        init = self.rpc(tokens.access, "initialize", _INITIALIZE_PARAMS)
        server = _json_object(init.get("serverInfo"))
        _passed("7a initialize", f"server {_text(server.get('name'))}")
        names = self.tool_names(tokens.access)
        _expect(names == _EXPECTED_TOOLS, f"tools/list: {sorted(names)}")
        _passed("7b tools/list", f"{len(names)} tools")
        metrics = self.call_list_metrics(tokens.access)
        _expect("error" not in metrics, f"list_metrics: {metrics.get('error')}")
        sources = _json_list(metrics.get("sources"))
        _expect(bool(sources), "list_metrics returned no sources")
        _passed("7c tools/call list_metrics", f"{len(sources)} source(s) with metrics")

    def rotation(
        self, client: _Client, tokens: _Tokens, grace_wait: int | None
    ) -> None:
        rotated = self.tokens_from(self.refresh(client, tokens.refresh), "refresh")
        _expect(rotated.refresh != tokens.refresh, "refresh: token was not rotated")
        _expect(bool(self.tool_names(rotated.access)), "rotated access token refused")
        _passed("8a refresh", f"new refresh {_shown(rotated.refresh)}")
        if grace_wait is None:
            print("SKIP 8b reuse after grace (--skip-grace-wait)", flush=True)
            return
        print(f"... waiting {grace_wait} s for the refresh grace to pass", flush=True)
        time.sleep(grace_wait)
        replay = self.refresh(client, tokens.refresh)
        _expect(
            replay.status_code == HTTPStatus.BAD_REQUEST
            and _error_of(replay) == "invalid_grant",
            f"reuse: expected 400 invalid_grant, got {_error_of(replay)}",
        )
        self.expect_mcp_401(rotated.access, "reuse")
        _passed("8b reuse after grace", "invalid_grant, family dead (access 401)")

    def revoke_flow(self) -> None:
        client, tokens = self.login()
        response = self.http.post(
            self.endpoints.revocation,
            data={"client_id": client.client_id, "token": tokens.refresh},
        )
        _expect(
            response.status_code == HTTPStatus.OK,
            f"revoke: HTTP {response.status_code}",
        )
        self.expect_mcp_401(tokens.access, "revoke")
        _passed("9 revoke", "200, access token now 401")

    def code_replay(self) -> None:
        client = self.register()
        verifier, challenge = _pkce_pair()
        code = self.code_for(client, challenge, announce=False)
        tokens = self.tokens_from(self.exchange(client, code, verifier), "token")
        replay = self.exchange(client, code, verifier)
        _expect(
            _error_of(replay) == "invalid_grant",
            f"code replay: expected invalid_grant, got {_error_of(replay)}",
        )
        self.expect_mcp_401(tokens.access, "code replay")
        _passed("10 code replay", "invalid_grant, family dead (access 401)")

    def pat(self, pat: str, *, eligible: bool) -> None:
        names = self.tool_names(pat)
        if eligible:
            _expect(names == _EXPECTED_TOOLS, f"PAT tools/list: {sorted(names)}")
            _passed("11 PAT tools/list", f"{_shown(pat)}: {len(names)} tools")
            return
        _expect(not names, f"ineligible PAT tools/list not empty: {sorted(names)}")
        denied = self.call_list_metrics(pat)
        # The denial (app/mcp/server.py NO_MCP_ACCESS) has no machine-readable reason
        # field, only its fixed `error` copy, which names the capability; match that.
        _expect(
            "mcp:use" in (_text(denied.get("error")) or ""),
            "tools/call was not denied",
        )
        _passed("N3 PAT without mcp:use", "empty tools/list, tools/call denied")

    def revoked_pat(self, pat: str) -> None:
        self.expect_mcp_401(pat, "revoked PAT", "initialize", _INITIALIZE_PARAMS)
        self.expect_mcp_401(pat, "revoked PAT")
        _passed("11b revoked PAT", f"{_shown(pat)}: initialize and tools/list 401")

    def register_limit(self) -> None:
        for _ in range(_REGISTER_ATTEMPTS):
            redirect = f"http://localhost:{_free_port()}/callback"
            response = self.register_request("atlas smoke limit", redirect)
            if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                _expect(
                    bool(response.headers.get("retry-after")),
                    "429 has no Retry-After",
                )
                _passed("12 register limit", "429 with Retry-After")
                return
        raise _CheckFailedError(f"register: no 429 after {_REGISTER_ATTEMPTS} attempts")

    def ineligible(self) -> None:
        client = self.register()
        _, challenge = _pkce_pair()
        txn = self.authorize(client, challenge, secrets.token_urlsafe(16))
        prompt = self.consent_prompt(txn)
        _expect(prompt.get("eligible") is False, "consent: user unexpectedly eligible")
        reason = _text(prompt.get("ineligible_reason"))
        _expect(reason == "no_mcp_use", f"consent: reason {reason}")
        _passed("N1 consent prompt", f"{_text(prompt.get('user_email'))} ineligible")
        response = self.decide(txn)
        detail = _json_object(_body_of(response).get("detail"))
        _expect(
            response.status_code == HTTPStatus.FORBIDDEN
            and _text(detail.get("reason")) == "no_mcp_use",
            f"consent approve: expected 403 no_mcp_use, got {response.status_code}",
        )
        _passed("N2 consent approve", "403 no_mcp_use")


# ---- entry point -----------------------------------------------------------------


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="End-to-end smoke test of the MCP OAuth door.",
        epilog=(
            f"Secrets come only from the environment: {_FIREBASE_ENV} (consent "
            f"bearer; not needed under AUTH_DISABLED), {_PAT_ENV} (step 11), "
            f"{_REVOKED_PAT_ENV} (step 11b)."
        ),
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help=(
            "the atlas origin, exactly as the server's ATLAS_PUBLIC_URL "
            "(e.g. http://localhost:8080); plain http only for a loopback host"
        ),
    )
    parser.add_argument(
        "--skip-grace-wait",
        action="store_true",
        help=f"skip the {_GRACE_WAIT_SECONDS} s wait and the refresh-reuse check",
    )
    parser.add_argument(
        "--check-register-limit",
        action="store_true",
        help=(
            "exhaust the /register budget (10/h) to see the 429; blocks DCR for ALL "
            "clients for 1 h on this deployment (per-source limits are global behind "
            "nginx/tunnel in 4a); needs --allow-shared-impact"
        ),
    )
    parser.add_argument(
        "--allow-shared-impact",
        action="store_true",
        help="confirm that --check-register-limit may block other users' DCR",
    )
    parser.add_argument(
        "--expect-ineligible",
        action="store_true",
        help="the consenting user lacks mcp:use: check the refusals instead",
    )
    args = parser.parse_args()
    problem = _base_url_problem(args.base_url)
    if problem is not None:
        parser.error(problem)
    if args.check_register_limit and not args.allow_shared_impact:
        parser.error("--check-register-limit also needs --allow-shared-impact")
    return args


def _run(http: httpx.Client, args: argparse.Namespace) -> None:
    base = str(args.base_url).rstrip("/")
    pat = os.environ.get(_PAT_ENV) or None
    revoked_pat = os.environ.get(_REVOKED_PAT_ENV) or None
    endpoints = _discover(http, base)
    smoke = _Smoke(http, base, endpoints, os.environ.get(_FIREBASE_ENV) or None)
    if args.expect_ineligible:
        smoke.ineligible()
        if pat:
            smoke.pat(pat, eligible=False)
    else:
        client, tokens = smoke.login(announce=True)
        smoke.mcp_calls(tokens)
        grace = None if args.skip_grace_wait else _GRACE_WAIT_SECONDS
        smoke.rotation(client, tokens, grace)
        smoke.revoke_flow()
        smoke.code_replay()
        if pat:
            smoke.pat(pat, eligible=True)
        else:
            print(f"SKIP 11 PAT (no {_PAT_ENV})", flush=True)
    if revoked_pat:
        smoke.revoked_pat(revoked_pat)
    else:
        print(f"SKIP 11b revoked PAT (no {_REVOKED_PAT_ENV})", flush=True)
    if args.check_register_limit:
        smoke.register_limit()


def main() -> int:
    args = _args()
    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as http:
            _run(http, args)
    except _CheckFailedError as exc:
        print(f"FAIL {exc}", flush=True)
        return 1
    except KeyboardInterrupt:
        print("FAIL interrupted", flush=True)
        return 1
    except Exception as exc:  # a FAIL line, never a traceback
        # The type only: messages and bodies may carry tokens, codes or txn ids.
        print(f"FAIL unexpected {type(exc).__name__}", flush=True)
        return 1
    print("ALL PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
