"""Settings invariants that protect production."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_auth_bypass_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="AUTH_DISABLED"):
        Settings(_env_file=None, environment="production", auth_disabled=True)


def test_auth_bypass_allowed_in_development() -> None:
    settings = Settings(_env_file=None, environment="development", auth_disabled=True)
    assert settings.auth_disabled


def test_bootstrap_admins_are_normalised() -> None:
    settings = Settings(
        _env_file=None, bootstrap_admins=" Ashik@YouGotAGift.com, ,ops@yougotagift.com "
    )
    assert settings.bootstrap_admin_list == [
        "ashik@yougotagift.com",
        "ops@yougotagift.com",
    ]


def test_session_max_age_defaults_to_24_hours() -> None:
    assert Settings(_env_file=None).session_max_age_hours == 24
