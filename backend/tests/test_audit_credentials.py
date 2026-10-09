"""Every atlas tool call is audited with the credential that ran it (D12)."""

from uuid import uuid4

from sqlmodel import col, select

from app.atlas import AtlasCaller, AtlasTools
from app.models.audit import AtlasAuditLog
from tests.fakes import StaticPolicy


async def test_audit_rows_carry_the_callers_token_and_client(db) -> None:
    user_id, token_id = uuid4(), uuid4()
    caller = AtlasCaller(
        user_id=user_id,
        auth_method="oauth",
        surface="mcp",
        token_id=token_id,
        client_id="client-1",
    )

    await AtlasTools(caller, StaticPolicy(), db=db).execute("list_metrics", {})

    row = (
        await db.execute(
            select(AtlasAuditLog).where(col(AtlasAuditLog.user_id) == user_id)
        )
    ).scalar_one()
    assert row.token_id == token_id
    assert row.client_id == "client-1"


async def test_web_calls_are_audited_without_a_credential(db) -> None:
    user_id = uuid4()
    caller = AtlasCaller(user_id=user_id, auth_method="web")

    await AtlasTools(caller, StaticPolicy(), db=db).execute("list_metrics", {})

    row = (
        await db.execute(
            select(AtlasAuditLog).where(col(AtlasAuditLog.user_id) == user_id)
        )
    ).scalar_one()
    assert row.token_id is None
    assert row.client_id is None
