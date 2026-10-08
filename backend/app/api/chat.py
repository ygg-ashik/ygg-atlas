import json
from collections.abc import AsyncGenerator, Sequence
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.agent import run_chat_turn
from app.database import get_db, get_session_factory
from app.identity import Principal, get_principal
from app.models.chat import ChatMessage, ChatSession

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

MAX_HISTORY_MESSAGES = 40


class CreateSessionRequest(BaseModel):
    title: str | None = None


class SendMessageRequest(BaseModel):
    content: str


class FeedbackRequest(BaseModel):
    rating: str  # 'up' | 'down'
    category: str | None = None  # 'inaccurate' | 'incomplete' | 'not_relevant'


async def _owned_session(
    session_id: UUID, principal: Principal, db: AsyncSession
) -> ChatSession:
    session = (
        await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    ).scalar_one_or_none()
    if session is None or session.user_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/sessions", response_model=ChatSession)
async def create_session(
    body: CreateSessionRequest,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> ChatSession:
    session = ChatSession(
        user_id=principal.user_id,
        user_uid=str(principal.user_id),
        user_email=principal.email,
        title=body.title or "New chat",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/sessions", response_model=list[ChatSession])
async def list_sessions(
    principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)
) -> Sequence[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(col(ChatSession.user_id) == principal.user_id)
        .order_by(col(ChatSession.updated_at).desc())
    )
    return result.scalars().all()


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessage])
async def list_messages(
    session_id: UUID,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> Sequence[ChatMessage]:
    await _owned_session(session_id, principal, db)
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(col(ChatMessage.created_at).asc())
        .limit(200)
    )
    return result.scalars().all()


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: UUID,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> None:
    session = await _owned_session(session_id, principal, db)
    messages = (
        (
            await db.execute(
                select(ChatMessage).where(ChatMessage.session_id == session_id)
            )
        )
        .scalars()
        .all()
    )
    for message in messages:
        await db.delete(message)
    await db.delete(session)
    await db.commit()


@router.patch("/messages/{message_id}/feedback", response_model=ChatMessage)
async def message_feedback(
    message_id: UUID,
    body: FeedbackRequest,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> ChatMessage:
    if body.rating not in ("up", "down"):
        raise HTTPException(status_code=422, detail="rating must be 'up' or 'down'")
    message = (
        await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    await _owned_session(message.session_id, principal, db)

    message.feedback_rating = body.rating
    message.feedback_category = body.category
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: UUID,
    body: SendMessageRequest,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    session = await _owned_session(session_id, principal, db)

    history_rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(col(ChatMessage.created_at).desc())
                .limit(MAX_HISTORY_MESSAGES)
            )
        )
        .scalars()
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]

    user_message = ChatMessage(session_id=session_id, role="user", content=body.content)
    db.add(user_message)
    if session.title == "New chat":
        session.title = body.content[:60]
    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()

    async def event_stream() -> AsyncGenerator[str, None]:
        # The request-scoped db session closes when the response handler returns,
        # so streaming uses its own session for the turn + persistence.
        async with get_session_factory()() as stream_db:
            async for event in run_chat_turn(
                user_uid=str(principal.user_id),
                session_id=session_id,
                content=body.content,
                history=history,
                db=stream_db,
            ):
                payload = event
                if event["type"] == "done":
                    assistant_message = ChatMessage(
                        session_id=session_id,
                        role="assistant",
                        content=event["content"],
                        provenance=event.get("provenance"),
                        blocks=event.get("blocks") or None,
                        model=event.get("model"),
                        token_usage=event.get("token_usage"),
                    )
                    stream_db.add(assistant_message)
                    await stream_db.commit()
                    payload = {**event, "message_id": str(assistant_message.id)}
                yield f"data: {json.dumps(payload, default=str)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
