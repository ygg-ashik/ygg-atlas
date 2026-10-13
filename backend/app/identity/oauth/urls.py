"""Pure URL rules: which redirects are allowed, how they are spelled, and when two
resource URLs name the same audience. No I/O."""

from collections.abc import Collection
from typing import Final
from urllib.parse import urlencode, urlsplit, urlunsplit

from pydantic import AnyHttpUrl, AnyUrl, ValidationError

MAX_REDIRECT_LENGTH: Final = 2000  # the stored column's width

_LOOPBACK_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "[::1]"})


def _parse_url(uri: str) -> AnyUrl | None:
    if len(uri) > MAX_REDIRECT_LENGTH:
        return None
    try:
        return AnyUrl(uri)
    except ValidationError:
        return None


def canonical_resource(url: str) -> str | None:
    """The SDK's own comparison (BearerAuthBackend._issued_for_this_resource): case and
    default port do not matter, one trailing slash aside. None if not a URL."""
    try:
        return str(AnyHttpUrl(url)).removesuffix("/")
    except ValidationError:
        return None


def same_audience(resource: str, audience: str) -> bool:
    """True when `audience` names our `resource`, by `canonical_resource`."""
    expected = canonical_resource(resource)
    return expected is not None and canonical_resource(audience) == expected


def redirect_allowed(uri: str, hosted: Collection[str]) -> bool:
    """Whether a redirect URI is allowed. Parsed with Pydantic AnyUrl (WHATWG, as
    the browser parses it), so there is no parser differential: loopback http on
    any port and path, or an exact approved https callback. Never userinfo (even
    `evil.com@localhost`, which lands on loopback: credentials-shaped text in a
    redirect is only a phishing aid) and never a fragment (RFC 6749 §3.1.2)."""
    url = _parse_url(uri)
    if url is None:
        return False
    if url.username is not None or url.password is not None:
        return False
    if url.fragment is not None:
        return False
    if url.scheme == "https":
        approved = {str(h) for h in map(_parse_url, hosted) if h is not None}
        return str(url) in approved
    return url.scheme == "http" and url.host in _LOOPBACK_HOSTS


def is_loopback_redirect(uri: str) -> bool:
    """True for an http redirect to localhost, 127.0.0.1 or [::1]."""
    url = _parse_url(uri)
    return url is not None and url.scheme == "http" and url.host in _LOOPBACK_HOSTS


def with_query(uri: str, **params: str | None) -> str:
    """`uri` with `params` added to its query; keeps the existing query, skips None."""
    extra = urlencode(
        {name: value for name, value in params.items() if value is not None}
    )
    if not extra:
        return uri
    parts = urlsplit(uri)
    query = f"{parts.query}&{extra}" if parts.query else extra
    return urlunsplit(parts._replace(query=query))


def canonical_redirect(uri: str) -> str:
    """The one spelling of a redirect we store and compare: `str(AnyUrl(uri))`.

    The SDK compares redirects as `str(AnyUrl)` on both sides
    (`OAuthClientMetadata.validate_redirect_uri`, `handlers/token.py`), so
    everything this service stores, returns in `RegisteredClient.redirect_uris`,
    binds into a code and redirects to is already in that form; a client may
    register `http://127.0.0.1:33418` and send `http://127.0.0.1:33418/`. Only
    called on URIs `redirect_allowed` accepted, or to normalise a comparison.
    """
    url = _parse_url(uri)
    return str(url) if url is not None else uri


def redirect_host(uri: str) -> str:
    url = _parse_url(uri)
    return (url.host or "") if url is not None else ""
