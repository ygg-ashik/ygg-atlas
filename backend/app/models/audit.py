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
    user_uid: str = Field(index=True)
    session_id: UUID | None = Field(default=None, index=True)
    surface: str = Field(default="chat")  # 'chat' | 'mcp' | 'api'
    tool: str
    arguments: dict | None = Field(default=None, sa_column=Column(JSON))
    success: bool = True
    error: str | None = None
    duration_ms: int | None = None
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )
