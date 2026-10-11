"""Redirect allowlist (D8), audience canonicalisation (D7) and query building: pure."""

import pytest

from app.identity.oauth import (
    canonical_resource,
    is_loopback_redirect,
    redirect_allowed,
    with_query,
)
from tests.identity.oauth_helpers import HOSTED_REDIRECT, RESOURCE

HOSTED = frozenset({HOSTED_REDIRECT})


@pytest.mark.parametrize(
    "uri",
    [
        "http://localhost:1234/callback",
        "http://localhost:35535/oauth/callback",
        "http://localhost:8765/callback",
        "http://127.0.0.1:9/x",
        "http://127.0.0.1:33418/",
        "http://[::1]:5/cb",
        "http://[::1]:9000/cb",
        "http://localhost/cb",  # no port
        "http://LOCALHOST:7777/x",  # host case does not matter
    ],
)
def test_loopback_redirects_are_allowed(uri: str) -> None:
    assert redirect_allowed(uri, HOSTED)
    assert is_loopback_redirect(uri)


def test_the_hosted_callback_is_allowed() -> None:
    assert redirect_allowed(HOSTED_REDIRECT, HOSTED)
    assert not is_loopback_redirect(HOSTED_REDIRECT)


def test_a_hosted_callback_is_allowed_only_when_configured() -> None:
    assert not redirect_allowed(HOSTED_REDIRECT, frozenset())


def test_a_misconfigured_http_hosted_callback_is_still_refused() -> None:
    assert not redirect_allowed(
        "http://claude.ai/cb", frozenset({"http://claude.ai/cb"})
    )


@pytest.mark.parametrize(
    "uri",
    [
        "http://atlas.example.com/cb",  # http to a non-loopback host
        "https://localhost/cb",  # https loopback is not a loopback redirect
        "http://localhost.evil.com/cb",  # loopback name as a label prefix
        "http://localhost.evil.com",
        "http://localhost./cb",  # trailing-dot host
        # userinfo: the browser goes to evil.com
        "http://localhost@evil.com/",
        # userinfo: the browser goes to localhost, but a redirect carrying
        # credentials-shaped text is a phishing aid and never legitimate: refused
        "http://evil.com@localhost/cb",
        "http://user:pass@localhost/cb",
        "http://127.0.0.1.nip.io/cb",
        "http://127.0.0.2/cb",
        "http://0.0.0.0/cb",
        "http://localhost:8080/cb#frag",  # fragments are forbidden (RFC 6749 §3.1.2)
        "http://localhost:8080/cb#",  # even an empty one
        "https://claude.ai/api/mcp/auth_callback/extra",
        "https://claude.ai/api/mcp/auth_callback#x",
        "https://claude.ai.evil.com/api/mcp/auth_callback",
        "https://evil.com/?https://claude.ai/api/mcp/auth_callback",
        "https://evil.com/cb",  # other https hosts
        "javascript:alert(1)",
        "custom-scheme://cb",
        "com.example.app:/oauth",
        "",
        "not a url",
        "http://localhost/" + "a" * 2000,  # longer than the stored column
    ],
)
def test_other_redirects_are_rejected(uri: str) -> None:
    assert not redirect_allowed(uri, HOSTED)


def test_backslash_is_parsed_like_a_browser() -> None:
    """WHATWG treats '\\' as '/' in special schemes, so the host is localhost and
    '@evil.com' is path. Pydantic parses as the browser does: no differential, and
    the redirect lands on loopback (harmless)."""
    assert redirect_allowed("http://localhost\\@evil.com/cb", HOSTED)


@pytest.mark.parametrize(
    "uri",
    ["https://claude.ai/api/mcp/auth_callback", "custom://x", "garbage", ""],
)
def test_non_loopback_uris_are_not_loopback(uri: str) -> None:
    assert not is_loopback_redirect(uri)


@pytest.mark.parametrize(
    ("given", "same"),
    [
        (RESOURCE, True),
        (RESOURCE + "/", True),
        ("http://LOCALHOST:8080/mcp-server/mcp/", True),
        ("http://localhost:8080/mcp-server", False),
        ("http://localhost:8080/mcp-server/mcp?x=1", False),
        ("https://localhost:8080/mcp-server/mcp", False),
        ("http://localhost:8081/mcp-server/mcp", False),
    ],
)
def test_canonical_resource(given: str, *, same: bool) -> None:
    assert (canonical_resource(given) == canonical_resource(RESOURCE)) is same


def test_canonical_resource_ignores_the_default_port() -> None:
    assert canonical_resource("http://localhost:80/x") == canonical_resource(
        "http://localhost/x"
    )


@pytest.mark.parametrize("garbage", ["", "not a url", "ftp://x/y", "mcp-server/mcp"])
def test_canonical_resource_of_garbage_is_none(garbage: str) -> None:
    assert canonical_resource(garbage) is None


def test_with_query_adds_params_and_skips_none() -> None:
    assert (
        with_query("http://localhost:1/cb", code="abc", state=None)
        == "http://localhost:1/cb?code=abc"
    )


def test_with_query_keeps_the_existing_query_and_encodes() -> None:
    assert (
        with_query("http://localhost:1/cb?a=1", state="x y&z")
        == "http://localhost:1/cb?a=1&state=x+y%26z"
    )


def test_with_query_without_params_returns_the_uri() -> None:
    assert with_query("http://localhost:1/cb?a=1") == "http://localhost:1/cb?a=1"
