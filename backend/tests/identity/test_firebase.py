"""The adapter verifies Firebase ID tokens without network calls or credentials."""

from typing import Any

import pytest
from firebase_admin import auth as fb_auth
from google.auth.exceptions import TransportError

from app.identity import firebase
from app.identity.errors import IdentityUnavailableError
from app.identity.tokens import InvalidTokenError

PROJECT = "ygg-atlas"


def _claims(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "aud": PROJECT,
        "sub": "fb-1",
        "email": "Sara@YouGotAGift.com",
        "email_verified": True,
        "name": "Sara",
        "auth_time": 1_700_000_000,
        "firebase": {"sign_in_provider": "google.com"},
    }
    claims.update(overrides)
    return claims


def _verifies_to(
    monkeypatch: pytest.MonkeyPatch, result: dict[str, Any] | Exception
) -> list[str | None]:
    audiences: list[str | None] = []

    def fake(token: str, request: object, audience: str | None = None) -> Any:
        audiences.append(audience)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(firebase.id_token, "verify_firebase_token", fake)
    return audiences


async def test_verify_maps_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    audiences = _verifies_to(monkeypatch, _claims())

    token = await firebase.FirebaseVerifier(PROJECT).verify("good")

    assert audiences == [PROJECT]  # the audience is pinned to our project
    assert token.uid == "fb-1"
    assert token.email == "sara@yougotagift.com"
    assert token.email_verified is True
    assert token.auth_time == 1_700_000_000
    assert token.sign_in_provider == "google.com"


async def test_bad_signature_or_expiry_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _verifies_to(monkeypatch, ValueError("Token expired"))
    with pytest.raises(InvalidTokenError):
        await firebase.FirebaseVerifier(PROJECT).verify("bad")


async def test_token_from_another_issuer_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _verifies_to(monkeypatch, _claims(iss="https://securetoken.google.com/other"))
    with pytest.raises(InvalidTokenError):
        await firebase.FirebaseVerifier(PROJECT).verify("foreign")


async def test_token_without_subject_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _verifies_to(monkeypatch, _claims(sub=""))
    with pytest.raises(InvalidTokenError):
        await firebase.FirebaseVerifier(PROJECT).verify("anonymous")


async def test_unconfigured_project_never_accepts_tokens() -> None:
    with pytest.raises(InvalidTokenError):
        await firebase.FirebaseVerifier("").verify("any")


async def test_certificate_outage_is_unavailable_not_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _verifies_to(monkeypatch, TransportError("certs unreachable"))
    with pytest.raises(IdentityUnavailableError):
        await firebase.FirebaseVerifier(PROJECT).verify("any")


async def test_revoke_calls_the_admin_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    revoked: list[str] = []

    def fake_revoke(uid: str, app: object) -> None:
        revoked.append(uid)

    monkeypatch.setattr(fb_auth, "revoke_refresh_tokens", fake_revoke)
    monkeypatch.setattr(firebase, "_admin_app", lambda project_id: object())

    await firebase.FirebaseVerifier(PROJECT).revoke("fb-1")

    assert revoked == ["fb-1"]
