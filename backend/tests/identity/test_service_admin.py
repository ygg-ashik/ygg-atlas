from app.config import Settings
from app.identity.repository import UserRepository
from app.identity.service import IdentityService


def _service(db) -> IdentityService:
    return IdentityService(
        UserRepository(db), Settings.model_validate({"environment": "test"})
    )


async def test_dev_user_is_created_once_as_viewer(db) -> None:
    first = await _service(db).ensure_dev_user()
    second = await _service(db).ensure_dev_user()

    assert first.user_id == second.user_id
    assert first.email == "dev@yougotagift.com"
    assert first.role == "viewer"
    assert first.auth_method == "dev"
