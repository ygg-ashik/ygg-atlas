from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, TIMESTAMP, Column
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ChatSession(SQLModel, table=True):
    __tablename__ = "chat_sessions"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_uid: str = Field(index=True)
    # Owner (atlas users.id). user_uid holds the same id as text for components that
    # still key on strings (guardrails, audit) until phase 2 passes a Principal.
    user_id: UUID | None = Field(default=None, foreign_key="users.id", index=True)
    user_email: str = Field(default="")
    title: str = Field(default="New chat")
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )
    updated_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"  # pyright: ignore[reportAssignmentType]  # sqlmodel types it as declared_attr

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    session_id: UUID = Field(foreign_key="chat_sessions.id", index=True)
    role: str  # 'user' | 'assistant'
    content: str
    provenance: list | None = Field(default=None, sa_column=Column(JSON))
    blocks: list | None = Field(  # clarify/artifact answer blocks (app.agent.blocks)
        default=None, sa_column=Column(JSON)
    )
    model: str | None = None
    token_usage: dict | None = Field(default=None, sa_column=Column(JSON))
    feedback_rating: str | None = None  # 'up' | 'down'
    feedback_category: str | None = None  # 'inaccurate' | 'incomplete' | 'not_relevant'
    created_at: datetime = Field(
        default_factory=_utcnow, sa_type=TIMESTAMP(timezone=True)
    )
