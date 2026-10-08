"""Settings invariants that protect production. They fail closed."""

import pytest
from pydantic import ValidationError

from app.config import Settings


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
