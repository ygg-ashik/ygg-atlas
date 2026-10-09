from uuid import uuid4

from app.agent.guardrails import check_input
from app.models.chat import ChatMessage, ChatSession


async def test_empty_message_blocked(db):
    verdict = await check_input("   ", uuid4(), db)
    assert not verdict.allowed


async def test_too_long_blocked(db):
    verdict = await check_input("x" * 5000, uuid4(), db)
    assert not verdict.allowed
    assert "too long" in verdict.reason.lower()


async def test_normal_message_allowed(db):
    verdict = await check_input("What was revenue last week?", uuid4(), db)
    assert verdict.allowed


async def test_daily_rate_limit(db):
    heavy = uuid4()
    session = ChatSession(user_id=heavy, user_email="h@yougotagift.com")
    db.add(session)
    await db.commit()
    for i in range(5):  # test env sets CHAT_DAILY_MESSAGE_LIMIT=5
        db.add(ChatMessage(session_id=session.id, role="user", content=f"q{i}"))
    await db.commit()

    verdict = await check_input("one more", heavy, db)
    assert not verdict.allowed
    assert "limit" in verdict.reason.lower()

    # other users are unaffected
    verdict = await check_input("hello", uuid4(), db)
    assert verdict.allowed
