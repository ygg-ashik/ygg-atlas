"""Token kinds, minting and hashing: the pure core of every MCP credential."""

import hashlib
import re

import pytest

from app.identity import api_tokens
from app.identity.api_tokens import (
    BEARER_KINDS,
    DISPLAY_PREFIX_LENGTH,
    TOKEN_PREFIXES,
    CredentialActor,
    TokenKind,
    display_prefix,
    hash_secret,
    kind_of,
    mint,
    mint_secret,
)

_BODY = "A" * 43


def test_every_kind_has_a_distinct_prefix() -> None:
    assert set(TOKEN_PREFIXES) == set(TokenKind)
    assert len(set(TOKEN_PREFIXES.values())) == len(TokenKind)
    assert TOKEN_PREFIXES[TokenKind.PAT] == "atl_pat_"
    assert TOKEN_PREFIXES[TokenKind.SERVICE] == "atl_svc_"
    assert TOKEN_PREFIXES[TokenKind.OAUTH_ACCESS] == "atl_oat_"
    assert TOKEN_PREFIXES[TokenKind.OAUTH_REFRESH] == "atl_ort_"


def test_prefixes_fit_the_display_prefix() -> None:
    for prefix in TOKEN_PREFIXES.values():
        assert len(prefix) < DISPLAY_PREFIX_LENGTH


def test_refresh_tokens_are_never_bearers() -> None:
    assert TokenKind.OAUTH_REFRESH not in BEARER_KINDS
    bearers = {TokenKind.PAT, TokenKind.SERVICE, TokenKind.OAUTH_ACCESS}
    assert bearers == BEARER_KINDS


def test_reason_and_event_names_fit_their_columns() -> None:
    reasons = [v for k, v in vars(api_tokens).items() if k.startswith("REVOKED_")]
    events = [v for k, v in vars(api_tokens).items() if k.startswith("EVENT_")]
    assert len(reasons) == 12
    assert len(events) == 13
    assert len(set(reasons)) == len(reasons)
    assert len(set(events)) == len(events)
    assert all(isinstance(r, str) and 0 < len(r) <= 32 for r in reasons)
    assert all(isinstance(e, str) and 0 < len(e) <= 48 for e in events)


@pytest.mark.parametrize("kind", list(TokenKind))
def test_mint_has_prefix_and_256_bits(kind: TokenKind) -> None:
    raw = mint(kind)
    prefix = TOKEN_PREFIXES[kind]
    assert raw.startswith(prefix)
    body = raw[len(prefix) :]
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", body)
    assert kind_of(raw) is kind


def test_mint_secret_has_no_prefix() -> None:
    secret = mint_secret()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", secret)
    assert kind_of(secret) is None


def test_mint_is_unique() -> None:
    assert len({mint(TokenKind.PAT) for _ in range(1000)}) == 1000
    assert len({mint_secret() for _ in range(1000)}) == 1000


def test_hash_is_sha256_hex() -> None:
    raw = mint(TokenKind.PAT)
    digest = hash_secret(raw)
    assert digest == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert raw not in digest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"atl_pat_{_BODY}", TokenKind.PAT),
        (f"atl_svc_{_BODY}", TokenKind.SERVICE),
        (f"atl_oat_{_BODY}", TokenKind.OAUTH_ACCESS),
        (f"atl_ort_{_BODY}", TokenKind.OAUTH_REFRESH),
        (f"atl_pat_{'a-b_' * 10}xyz", TokenKind.PAT),
        (f"atl_xyz_{_BODY}", None),
        (f"atl_pat_{'A' * 42}", None),
        (f"atl_pat_{'A' * 44}", None),
        (f"atl_pat_{'A' * 42}+", None),
        (f"atl_pat_{'A' * 42}/", None),
        (f"atl_pat_{'A' * 42}=", None),
        (f"atl_pat_{'A' * 42}\n", None),
        ("", None),
        ("atl_pat_", None),
        (f"Bearer atl_pat_{_BODY}", None),
        (f"ATL_PAT_{_BODY}", None),
        ("eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl", None),
    ],
)
def test_kind_of_accepts_only_well_formed_tokens(
    raw: str, expected: TokenKind | None
) -> None:
    assert kind_of(raw) is expected


@pytest.mark.parametrize("kind", list(TokenKind))
def test_display_prefix_never_reveals_the_body(kind: TokenKind) -> None:
    raw = mint(kind)
    shown = display_prefix(raw)
    assert shown == raw[:DISPLAY_PREFIX_LENGTH]
    assert shown.startswith(TOKEN_PREFIXES[kind])
    # At most 6 body characters (36 bits) are shown; the rest stays secret.
    assert len(shown) - len(TOKEN_PREFIXES[kind]) <= 6
    assert raw[DISPLAY_PREFIX_LENGTH:] not in shown


def test_display_prefix_of_a_malformed_value_is_short() -> None:
    assert display_prefix("eyJhbGciOiJSUzI1NiJ9.payload.sig") == "eyJhbG"
    assert display_prefix("") == ""


def test_credential_actor_is_immutable() -> None:
    actor = CredentialActor(user_id=None, via="system")
    with pytest.raises(AttributeError):
        actor.via = "api"  # type: ignore[misc]  # asserting the dataclass is frozen
