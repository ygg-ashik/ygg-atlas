"""The deprecated app.middleware shim must keep in-flight callers working."""

from uuid import UUID

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.middleware import AuthUser, get_current_user


async def test_shim_returns_atlas_user_id_and_email(db) -> None:
    app = FastAPI()

    @app.get("/legacy")
    async def legacy(user: AuthUser = Depends(get_current_user)) -> dict[str, str]:
        return {"uid": user.uid, "email": user.email}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/legacy")).json()

    assert body["email"] == "dev@yougotagift.com"
    assert UUID(body["uid"])  # an atlas user id, not the old "dev-user"
