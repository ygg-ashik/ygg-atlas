from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, TIMESTAMP, Column
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AtlasAuditLog(SQLModel, table=True):
    """Audit record for every atlas tool execution — chat agent or MCP client."""

    __tablename__ = "atlas_audit_log"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Legacy owner key: a Firebase uid before migration 0002, the atlas id after it.
    # Append-only, so it is kept; new code reads user_id.
    user_uid: str = Field(index=True)
    user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    auth_method: str | None = Field(default=None, max_length=16)
    session_id: UUID | None = Field(default=None, index=True)
    surface: str = Field(default="chat")  # 'chat' | 'mcp' | 'api'
    tool: str
    arguments: dict | None = Field(default=None, sa_column=Column(JSON))
    success: bool = True
    error: str | None = None
    decision: str = Field(default="allow", max_length=8)  # 'allow' | 'deny'
    deny_reason: str | None = Field(default=None, max_length=200)
    duration_ms: int | None = None
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )
