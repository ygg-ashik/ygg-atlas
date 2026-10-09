"""Settings invariants that protect production. They fail closed."""

import pytest
from pydantic import ValidationError

from app import config
from app.config import Settings
from app.identity import api_tokens


@pytest.fixture(autouse=True)
def _no_ambient_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest exports test-suite env vars; these tests check the bare defaults.
    for name in ("ENVIRONMENT", "AUTH_DISABLED", "FIREBASE_PROJECT_ID"):
        monkeypatch.delenv(name, raising=False)


def test_auth_bypass_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="AUTH_DISABLED"):
        Settings.model_validate({"environment": "production", "auth_disabled": True})


def test_auth_bypass_refused_when_environment_unset() -> None:
    with pytest.raises(ValidationError, match="AUTH_DISABLED"):
        Settings.model_validate({"auth_disabled": True})


def test_auth_bypass_allowed_in_development() -> None:
    settings = Settings.model_validate(
        {"environment": "development", "auth_disabled": True}
    )
    assert settings.auth_disabled


def test_environment_defaults_to_production() -> None:
    # A deployment that forgets ENVIRONMENT gets production rules.
    settings = Settings.model_validate({"firebase_project_id": "p"})
    assert settings.environment == "production"


def test_production_requires_firebase_project() -> None:
    with pytest.raises(ValidationError, match="FIREBASE_PROJECT_ID"):
        Settings.model_validate({"environment": "production"})


def test_bootstrap_admins_are_normalised() -> None:
    settings = Settings.model_validate(
        {
            "environment": "test",
            "bootstrap_admins": " Ashik@YouGotAGift.com, ,ops@yougotagift.com ",
        }
    )
    assert settings.bootstrap_admin_list == [
        "ashik@yougotagift.com",
        "ops@yougotagift.com",
    ]


def test_session_max_age_defaults_to_24_hours() -> None:
    assert Settings.model_validate({"environment": "test"}).session_max_age_hours == 24


# --- MCP auth (phase 4): public URL, hosted redirects, PAT lifetimes ---


def test_public_url_defaults_to_the_tunnel() -> None:
    settings = Settings.model_validate({"environment": "test"})
    assert settings.atlas_public_url == "http://localhost:8080"
    assert settings.mcp_issuer_url == "http://localhost:8080/mcp-server"
    assert settings.mcp_resource_url == "http://localhost:8080/mcp-server/mcp"
    assert settings.oauth_consent_url == "http://localhost:8080/oauth/consent"


def test_public_url_trailing_slash_is_dropped() -> None:
    settings = Settings.model_validate(
        {"environment": "test", "atlas_public_url": " http://localhost:8080/ "}
    )
    assert settings.atlas_public_url == "http://localhost:8080"
    assert settings.mcp_issuer_url == "http://localhost:8080/mcp-server"


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("http://atlas.example.com", False),
        ("http://10.0.0.5:8080", False),
        ("http://[::1]:8080", False),
        ("ftp://localhost:8080", False),
        ("http://127.0.0.1:8080", True),
        ("http://localhost", True),
        ("https://atlas.example.com", True),
    ],
)
def test_public_url_http_only_for_loopback(url: str, ok: bool) -> None:
    data = {"environment": "test", "atlas_public_url": url}
    if ok:
        assert Settings.model_validate(data).atlas_public_url == url
    else:
        with pytest.raises(ValidationError, match="ATLAS_PUBLIC_URL"):
            Settings.model_validate(data)


@pytest.mark.parametrize(
    "url",
    [
        "https://atlas.example.com/atlas",
        "https://atlas.example.com/?x=1",
        "https://atlas.example.com#frag",
        "https://user:pw@atlas.example.com",
        "https://user@atlas.example.com",
        "https://",
        "not a url",
        "https://atlas.example.com:443",
        "http://localhost:",
        "http://localhost:0",
        "https://a b.com",
        "https://Atlas.Example.com",
        "HTTPS://atlas.example.com",
        "https://atlas.example.com.",
    ],
)
def test_public_url_rejects_path_query_fragment_userinfo(url: str) -> None:
    with pytest.raises(ValidationError, match="ATLAS_PUBLIC_URL"):
        Settings.model_validate({"environment": "test", "atlas_public_url": url})


def test_hosted_connectors_only_with_https() -> None:
    local = Settings.model_validate({"environment": "test"})
    hosted = Settings.model_validate(
        {"environment": "test", "atlas_public_url": "https://atlas.example.com"}
    )
    assert not local.hosted_connectors_enabled
    assert hosted.hosted_connectors_enabled


def test_hosted_redirects_must_be_https() -> None:
    with pytest.raises(ValidationError, match="OAUTH_HOSTED_REDIRECT_URIS"):
        Settings.model_validate(
            {
                "environment": "test",
                "oauth_hosted_redirect_uris": "https://claude.ai/cb,http://evil.example/cb",
            }
        )


@pytest.mark.parametrize(
    "uri",
    [
        "https://user@claude.ai/api/mcp/auth_callback",
        "https://user:pw@claude.ai/cb",
        "https://claude.ai/cb#frag",
        "https://claude.ai/cb#",
    ],
)
def test_hosted_redirects_reject_userinfo_and_fragments(uri: str) -> None:
    with pytest.raises(ValidationError, match="OAUTH_HOSTED_REDIRECT_URIS"):
        Settings.model_validate(
            {"environment": "test", "oauth_hosted_redirect_uris": uri}
        )


def test_pat_max_days_matches_the_token_ceiling() -> None:
    # config may not import identity, so the ceiling is duplicated; keep them equal.
    assert config._MAX_TOKEN_DAYS == api_tokens.MAX_TOKEN_DAYS


def test_hosted_redirect_list_splits_and_strips() -> None:
    default = Settings.model_validate({"environment": "test"})
    assert default.hosted_redirect_uri_list == [
        "https://claude.ai/api/mcp/auth_callback"
    ]
    settings = Settings.model_validate(
        {
            "environment": "test",
            "oauth_hosted_redirect_uris": (
                " https://a.example/cb , ,https://b.example/cb "
            ),
        }
    )
    assert settings.hosted_redirect_uri_list == [
        "https://a.example/cb",
        "https://b.example/cb",
    ]


def test_pat_days_default() -> None:
    settings = Settings.model_validate({"environment": "test"})
    assert (settings.pat_default_days, settings.pat_max_days) == (90, 365)


@pytest.mark.parametrize(
    ("default_days", "max_days"),
    [(0, 365), (31, 30), (90, 366), (1, 0)],
)
def test_pat_day_bounds(default_days: int, max_days: int) -> None:
    with pytest.raises(ValidationError, match="PAT_"):
        Settings.model_validate(
            {
                "environment": "test",
                "pat_default_days": default_days,
                "pat_max_days": max_days,
            }
        )
