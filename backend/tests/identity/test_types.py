from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from app.atlas.policy import AtlasCaller
from app.identity.principal import Principal
from app.identity.tokens import VerifiedToken


def test_principal_is_immutable() -> None:
    principal = Principal(
        user_id=uuid4(),
        email="a@yougotagift.com",
        display_name="A",
        role="viewer",
        kind="human",
        tenant="ygg",
        auth_method="web",
    )
    with pytest.raises(FrozenInstanceError):
        principal.role = "admin"  # type: ignore[misc]  # asserting the dataclass is frozen


def test_verified_token_fields() -> None:
    token = VerifiedToken(
        uid="fb-1",
        email="a@yougotagift.com",
        email_verified=True,
        name="A",
        auth_time=1,
        sign_in_provider="google.com",
    )
    assert token.email == "a@yougotagift.com"


def test_principal_credential_ids_default_to_none() -> None:
    principal = Principal(
        user_id=uuid4(),
        email="a@yougotagift.com",
        display_name="A",
        role="viewer",
        kind="human",
        tenant="ygg",
        auth_method="web",
    )
    assert principal.token_id is None
    assert principal.client_id is None


def test_atlas_caller_credential_ids_default_to_none() -> None:
    caller = AtlasCaller(user_id=uuid4(), auth_method="web")
    assert caller.token_id is None
    assert caller.client_id is None
    token_id = uuid4()
    mcp_caller = AtlasCaller(
        user_id=uuid4(),
        auth_method="oauth",
        surface="mcp",
        token_id=token_id,
        client_id="client-1",
    )
    assert (mcp_caller.token_id, mcp_caller.client_id) == (token_id, "client-1")
