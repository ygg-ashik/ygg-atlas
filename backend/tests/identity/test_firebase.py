"""The adapter maps firebase_admin results and failures without network calls."""

import pytest
from firebase_admin import auth as fb_auth

from app.identity import firebase
from app.identity.errors import IdentityUnavailableError
from app.identity.tokens import InvalidTokenError


def _no_app(project_id: str) -> object:
    return object()


async def test_verify_maps_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_verify(token: str, app: object) -> dict[str, object]:
        assert token == "good"
        return {
            "uid": "fb-1",
            "email": "Sara@YouGotAGift.com",
            "email_verified": True,
            "name": "Sara",
            "auth_time": 1_700_000_000,
            "firebase": {"sign_in_provider": "google.com"},
        }

    monkeypatch.setattr(fb_auth, "verify_id_token", fake_verify)
    monkeypatch.setattr(firebase, "_app", _no_app)

    token = await firebase.FirebaseVerifier("proj").verify("good")

    assert token.uid == "fb-1"
    assert token.email == "sara@yougotagift.com"
    assert token.email_verified is True
    assert token.auth_time == 1_700_000_000
    assert token.sign_in_provider == "google.com"


async def test_verify_turns_sdk_errors_into_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_verify(token: str, app: object) -> dict[str, object]:
        raise ValueError("malformed")

    monkeypatch.setattr(fb_auth, "verify_id_token", fake_verify)
    monkeypatch.setattr(firebase, "_app", _no_app)

    with pytest.raises(InvalidTokenError):
        await firebase.FirebaseVerifier("proj").verify("bad")


async def test_revoke_calls_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    revoked: list[str] = []

    def fake_revoke(uid: str, app: object) -> None:
        revoked.append(uid)

    monkeypatch.setattr(fb_auth, "revoke_refresh_tokens", fake_revoke)
    monkeypatch.setattr(firebase, "_app", _no_app)

    await firebase.FirebaseVerifier("proj").revoke("fb-1")

    assert revoked == ["fb-1"]


async def test_certificate_outage_is_unavailable_not_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_verify(token: str, app: object) -> dict[str, object]:
        raise fb_auth.CertificateFetchError("down", cause=None)

    monkeypatch.setattr(fb_auth, "verify_id_token", fake_verify)
    monkeypatch.setattr(firebase, "_app", _no_app)

    with pytest.raises(IdentityUnavailableError):
        await firebase.FirebaseVerifier("proj").verify("any")
