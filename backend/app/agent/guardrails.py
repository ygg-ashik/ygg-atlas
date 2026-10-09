"""Pre-flight guardrails for chat turns.

Cheap, deterministic, enforced before the model runs.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.config import get_settings
from app.models.chat import ChatMessage, ChatSession


@dataclass(frozen=True)
class GuardrailVerdict:
    allowed: bool
    reason: str = ""


async def check_input(
    content: str, user_id: UUID, db: AsyncSession
) -> GuardrailVerdict:
    settings = get_settings()

    if not content or not content.strip():
        return GuardrailVerdict(False, "Empty message")

    if len(content) > settings.max_input_chars:
        return GuardrailVerdict(
            False, f"Message too long (max {settings.max_input_chars} characters)"
        )

    midnight = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    stmt = (
        select(func.count())
        .select_from(ChatMessage)
        .join(ChatSession, col(ChatMessage.session_id) == col(ChatSession.id))
        .where(
            col(ChatSession.user_id) == user_id,
            col(ChatMessage.role) == "user",
            col(ChatMessage.created_at) >= midnight,
        )
    )
    count = (await db.execute(stmt)).scalar_one()
    if count >= settings.chat_daily_message_limit:
        return GuardrailVerdict(
            False,
            f"Daily message limit reached ({settings.chat_daily_message_limit}/day). "
            "Try again tomorrow.",
        )

    return GuardrailVerdict(True)
