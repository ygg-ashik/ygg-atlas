from functools import lru_cache
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://atlas:atlas@localhost:5433/ygg_atlas"

    # LLM provider: set exactly one key; anthropic wins if both are set.
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    agent_model: str = ""  # optional override; sensible per-provider default otherwise

    firebase_project_id: str = ""
    allowed_email_domain: str = "yougotagift.com"
    auth_disabled: bool = False
    # Fails closed: an unset ENVIRONMENT means production rules.
    environment: Literal["development", "test", "production"] = "production"
    # Comma-separated emails made admin at startup (idempotent). Spec §3.3.
    bootstrap_admins: str = ""
    # Web sessions are capped server-side from the token's auth_time. Spec §3.1.
    session_max_age_hours: int = 24

    # Source-specific config lives in each plugin's Settings
    # (app/sources/<id>/manifest.py)

    chat_daily_message_limit: int = 200
    agent_max_tool_rounds: int = 6
    max_input_chars: int = 4000

    # MCP auth (phase 4). The URL users type into their MCP client: scheme, host and
    # optional port, no path. Issuer, resource and consent URLs derive from it.
    atlas_public_url: str = "http://localhost:8080"
    # Comma-separated exact https redirect URIs of hosted MCP clients (DCR allowlist).
    oauth_hosted_redirect_uris: str = "https://claude.ai/api/mcp/auth_callback"
    pat_default_days: int = 90
    pat_max_days: int = 365

    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # HMAC key for pseudonymised breakdown labels. A secret: never log it.
    # Empty degrades pseudonymise to suppress (fail closed).
    atlas_pseudonym_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def bootstrap_admin_list(self) -> list[str]:
        return [
            e.strip().lower() for e in self.bootstrap_admins.split(",") if e.strip()
        ]

    @property
    def mcp_issuer_url(self) -> str:
        return f"{self.atlas_public_url}/mcp-server"

    @property
    def mcp_resource_url(self) -> str:
        return f"{self.atlas_public_url}/mcp-server/mcp"

    @property
    def oauth_consent_url(self) -> str:
        return f"{self.atlas_public_url}/oauth/consent"

    @property
    def hosted_redirect_uri_list(self) -> list[str]:
        return [
            u.strip() for u in self.oauth_hosted_redirect_uris.split(",") if u.strip()
        ]

    @property
    def hosted_connectors_enabled(self) -> bool:
        return urlsplit(self.atlas_public_url).scheme == "https"

    @field_validator("atlas_public_url")
    @classmethod
    def _valid_public_url(cls, value: str) -> str:
        url = value.strip().removesuffix("/")
        problem = _public_url_problem(url)
        if problem:
            msg = f"ATLAS_PUBLIC_URL {problem}"
            raise ValueError(msg)
        return url

    @field_validator("oauth_hosted_redirect_uris")
    @classmethod
    def _hosted_redirects_are_https(cls, value: str) -> str:
        for uri in (u.strip() for u in value.split(",")):
            if uri and not _is_https_url(uri):
                msg = (
                    "OAUTH_HOSTED_REDIRECT_URIS entries must be https URLs "
                    "without userinfo or fragment"
                )
                raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _pat_lifetimes_in_bounds(self) -> Self:
        if not 1 <= self.pat_max_days <= _MAX_TOKEN_DAYS:
            msg = f"PAT_MAX_DAYS must be between 1 and {_MAX_TOKEN_DAYS}"
            raise ValueError(msg)
        if not 1 <= self.pat_default_days <= self.pat_max_days:
            msg = "PAT_DEFAULT_DAYS must be between 1 and PAT_MAX_DAYS"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _fail_closed_outside_development(self) -> Self:
        if self.auth_disabled and self.environment == "production":
            msg = "AUTH_DISABLED=true needs ENVIRONMENT=development or test"
            raise ValueError(msg)
        if self.environment == "production" and not self.firebase_project_id:
            msg = "FIREBASE_PROJECT_ID is required when ENVIRONMENT=production"
            raise ValueError(msg)
        return self

    @property
    def llm_provider(self) -> str:
        return (
            "anthropic"
            if self.anthropic_api_key or not self.openai_api_key
            else "openai"
        )

    @property
    def resolved_agent_model(self) -> str:
        if self.agent_model:
            return self.agent_model
        return "claude-sonnet-4-6" if self.llm_provider == "anthropic" else "gpt-4.1"


# Mirrors app.identity.api_tokens.MAX_TOKEN_DAYS (config may not import features).
_MAX_TOKEN_DAYS = 365
# The MCP SDK accepts an http issuer only on these hosts (validate_issuer_url).
_HTTP_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1"})


def _public_url_problem(url: str) -> str | None:
    """Why `url` cannot be the public origin, or None when it can."""
    try:
        parts = urlsplit(url)
        port = parts.port  # raises ValueError on a malformed port
    except ValueError:
        return "is not a valid URL"
    if parts.scheme not in ("http", "https"):
        return "must use http or https"
    if not parts.hostname or "@" in parts.netloc or parts.hostname.endswith("."):
        return "needs a host (no trailing dot) and no userinfo"
    if (
        port == 0
        or url != f"{parts.scheme}://{parts.netloc.lower()}"
        or not _is_canonical_origin(url)
    ):
        return "must be canonical lowercase scheme://host[:port], no path or query"
    if parts.scheme == "http" and parts.hostname not in _HTTP_LOOPBACK_HOSTS:
        return "may use http only for localhost or 127.0.0.1"
    return None


def _is_canonical_origin(url: str) -> bool:
    """True when Pydantic (the MCP SDK's URL parser) renders `url` unchanged.

    Rejects default ports, empty ports and hosts that do not parse, so the issuer and
    resource we advertise equal the SDK's canonical form (D7).
    """
    try:
        return str(AnyHttpUrl(url)).removesuffix("/") == url
    except ValidationError:
        return False


def _is_https_url(uri: str) -> bool:
    """An exact https redirect URI: a host, no userinfo, no fragment."""
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and bool(parts.hostname)
        and "@" not in parts.netloc
        and "#" not in uri
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
