"""Deploy configuration invariants for MCP authentication (phase 4, Task 11).

Text checks over files the backend does not load at runtime: the frontend nginx
config, `backend/.env.example` and the OAuth discovery routes. They keep the proxy
in line with what the backend needs (the port in `Host`, unbuffered streams, the
discovery documents) and keep the consent transaction id out of logs and frames.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
NGINX_CONF = REPO / "frontend" / "nginx.conf"
ENV_EXAMPLE = REPO / "backend" / ".env.example"
OAUTH_ROUTES = REPO / "backend" / "app" / "mcp" / "oauth_routes.py"


def _strip_comments(text: str) -> str:
    """Drop whole-line comments ("#" also appears inside regexes, so not mid-line)."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _block(conf: str, opener: str) -> str:
    """The body of the first `<opener> {...}` block (balanced braces)."""
    found = re.search(rf"(?m)^\s*{re.escape(opener)}\s*\{{", conf)
    assert found is not None, f"missing nginx block: {opener}"
    brace = found.end() - 1
    depth = 0
    for index in range(brace, len(conf)):
        if conf[index] == "{":
            depth += 1
        elif conf[index] == "}":
            depth -= 1
            if depth == 0:
                return conf[brace + 1 : index]
    raise AssertionError(f"unbalanced braces after: {opener}")


def _directives(body: str) -> list[str]:
    """Top-level directives of a block, whitespace-normalised."""
    return [" ".join(part.split()) for part in body.split(";") if part.strip()]


@pytest.fixture(scope="module")
def nginx() -> str:
    return _strip_comments(NGINX_CONF.read_text())


def test_nginx_proxies_mcp_and_discovery_with_the_port(nginx: str) -> None:
    mcp = _directives(_block(nginx, "location /mcp-server/"))
    discovery = _directives(_block(nginx, "location ^~ /.well-known/oauth-"))
    for body in (mcp, discovery):
        assert "proxy_pass http://backend:8081" in body
        # $http_host keeps the port for the DNS-rebinding check (C1, D26).
        assert "proxy_set_header Host $http_host" in body
        assert "proxy_buffering off" in body
        assert "proxy_cache off" in body
    assert "proxy_read_timeout 3600s" in mcp


def test_discovery_location_covers_every_backend_discovery_path(nginx: str) -> None:
    paths = set(re.findall(r"\"(/\.well-known/[^\"]*)\"", OAUTH_ROUTES.read_text()))
    assert paths, "no discovery paths found in oauth_routes.py"
    assert all(path.startswith("/.well-known/oauth-") for path in paths)
    # Narrowed so an outer TLS proxy can keep other /.well-known/ paths (ACME).
    assert "location /.well-known/ " not in nginx


def test_consent_page_is_not_frameable_or_logged(nginx: str) -> None:
    page = _directives(_block(nginx, "location ~ ^/oauth/consent/?$"))
    assert 'add_header X-Frame-Options "DENY" always' in page
    assert (
        "add_header Content-Security-Policy \"frame-ancestors 'none'\" always" in page
    )
    assert 'add_header Referrer-Policy "no-referrer" always' in page
    assert 'add_header Cache-Control "no-store" always' in page
    shell = _directives(_block(nginx, "location /"))
    assert 'add_header X-Frame-Options "DENY" always' in shell

    uri_map = _block(nginx, "map $request_uri $atlas_log_uri")
    assert "~^/oauth/consent(/|[?#]|$) /oauth/consent" in " ".join(uri_map.split())
    assert "~^/api/v1/oauth/consent/ /api/v1/oauth/consent/-" in " ".join(
        uri_map.split()
    )
    referer_map = " ".join(
        _block(nginx, "map $http_referer $atlas_log_referer").split()
    )
    assert "~/oauth/consent -" in referer_map
    assert '"" -' in referer_map
    statement = nginx[nginx.index("log_format atlas") :].split(";", maxsplit=1)[0]
    log_format = " ".join(statement.split())
    assert "$atlas_log_uri" in log_format
    assert "$atlas_log_referer" in log_format
    assert "$request " not in log_format
    assert "$http_referer" not in log_format
    assert "access_log /var/log/nginx/access.log atlas" in " ".join(nginx.split())

    consent_api = _directives(_block(nginx, "location ^~ /api/v1/oauth/consent"))
    assert "error_log /var/log/nginx/error.log crit" in consent_api


def test_env_example_has_the_public_url_and_no_shared_token() -> None:
    settings = dict(
        line.split("=", 1)
        for line in ENV_EXAMPLE.read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    assert settings["ATLAS_PUBLIC_URL"] == "http://localhost:8080"
    assert settings["OAUTH_HOSTED_REDIRECT_URIS"] == (
        "https://claude.ai/api/mcp/auth_callback"
    )
    assert settings["PAT_DEFAULT_DAYS"] == "90"
    assert settings["PAT_MAX_DAYS"] == "365"
    text = ENV_EXAMPLE.read_text()
    assert "ATLAS_MCP_TOKEN" not in text
    assert "MCP_SERVICE_EMAIL" not in text
