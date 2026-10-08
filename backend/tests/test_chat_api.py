"""API tests: auth-disabled dev user, fake agent for the streaming endpoint."""

import json
from uuid import uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.api.chat as chat_module
from app.main import app as asgi_app
from app.models.chat import ChatSession
from tests.access_helpers import add_grant, make_user


@pytest_asyncio.fixture
async def api(db, monkeypatch):
    async def fake_run_chat_turn(tools, content, history, db, client=None):
        yield {"type": "token", "content": "42 "}
        yield {"type": "token", "content": "AED"}
        yield {
            "type": "done",
            "content": "42 AED",
            "provenance": [
                {"tool": "query_metric", "source": "demo", "metric_id": "revenue"}
            ],
            "blocks": [
                {
                    "kind": "clarify",
                    "question": "Which?",
                    "options": [
                        {"label": "A", "metric_id": None},
                        {"label": "B", "metric_id": None},
                    ],
                }
            ],
            "model": "test-model",
            "token_usage": {"input_tokens": 1, "output_tokens": 2},
        }

    monkeypatch.setattr(chat_module, "run_chat_turn", fake_run_chat_turn)

    transport = ASGITransport(app=asgi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_session_crud(api):
    created = (
        await api.post("/api/v1/chat/sessions", json={"title": "Weekly numbers"})
    ).json()
    assert created["title"] == "Weekly numbers"
    me = (await api.get("/api/v1/me")).json()
    assert created["user_id"] == me["user_id"]

    sessions = (await api.get("/api/v1/chat/sessions")).json()
    assert any(s["id"] == created["id"] for s in sessions)

    messages = (await api.get(f"/api/v1/chat/sessions/{created['id']}/messages")).json()
    assert messages == []

    resp = await api.delete(f"/api/v1/chat/sessions/{created['id']}")
    assert resp.status_code == 204
    sessions = (await api.get("/api/v1/chat/sessions")).json()
    assert not any(s["id"] == created["id"] for s in sessions)


async def test_send_message_streams_sse_and_persists(api):
    session = (await api.post("/api/v1/chat/sessions", json={})).json()

    resp = await api.post(
        f"/api/v1/chat/sessions/{session['id']}/messages",
        json={"content": "What was revenue last week?"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = [
        json.loads(line[len("data: ") :])
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]
    assert [e["type"] for e in events] == ["token", "token", "done"]
    assert events[-1]["provenance"][0]["metric_id"] == "revenue"
    assert "message_id" in events[-1]

    messages = (await api.get(f"/api/v1/chat/sessions/{session['id']}/messages")).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "42 AED"
    assert messages[1]["provenance"][0]["metric_id"] == "revenue"

    # first message set the session title
    sessions = (await api.get("/api/v1/chat/sessions")).json()
    assert sessions[0]["title"].startswith("What was revenue")


async def test_feedback(api):
    session = (await api.post("/api/v1/chat/sessions", json={})).json()
    await api.post(
        f"/api/v1/chat/sessions/{session['id']}/messages", json={"content": "q"}
    )
    messages = (await api.get(f"/api/v1/chat/sessions/{session['id']}/messages")).json()
    assistant_id = messages[1]["id"]

    resp = await api.patch(
        f"/api/v1/chat/messages/{assistant_id}/feedback",
        json={"rating": "down", "category": "inaccurate"},
    )
    assert resp.status_code == 200
    assert resp.json()["feedback_rating"] == "down"

    resp = await api.patch(
        f"/api/v1/chat/messages/{assistant_id}/feedback", json={"rating": "sideways"}
    )
    assert resp.status_code == 422


async def test_session_isolation_404_for_foreign_session(api, db):
    foreign = ChatSession(user_id=uuid4(), user_email="x@yougotagift.com")
    db.add(foreign)
    await db.commit()
    await db.refresh(foreign)

    resp = await api.get(f"/api/v1/chat/sessions/{foreign.id}/messages")
    assert resp.status_code == 404


async def test_healthz(api):
    resp = await api.get("/healthz")
    assert resp.json() == {"status": "ok"}


async def test_blocks_are_streamed_and_persisted(api):
    session = (await api.post("/api/v1/chat/sessions", json={})).json()
    resp = await api.post(
        f"/api/v1/chat/sessions/{session['id']}/messages", json={"content": "revenue?"}
    )
    events = [
        json.loads(line[6:])
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]
    assert events[-1]["blocks"][0]["kind"] == "clarify"
    messages = (await api.get(f"/api/v1/chat/sessions/{session['id']}/messages")).json()
    assert messages[1]["blocks"][0]["question"] == "Which?"


async def test_chat_needs_the_chat_capability(api, db):
    dev = await make_user(db, "dev@yougotagift.com")
    await add_grant(db, dev, "chat:use", effect="deny", kind="capability")
    resp = await api.get("/api/v1/chat/sessions")
    assert resp.status_code == 403
    assert "chat:use" in resp.json()["detail"]
