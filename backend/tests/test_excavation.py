import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.db import Conversation, ExcavationRecord, Message, get_session, initialize_database
from backend.app.main import app
from backend.app.query_builder import build_query
from backend.app.schemas import Intent
from backend.app.ollama import CHAT_PROMPT, OUT_OF_SCOPE_REPLY, chat_reply, classify_question, fallback_intent


@pytest.fixture(scope="module", autouse=True)
def database():
    initialize_database()


def test_seed_is_exact_and_idempotent():
    initialize_database()
    with get_session() as session:
        assert session.scalar(select(func.count()).select_from(ExcavationRecord)) == 56


def test_date_lookup_and_aggregates():
    with get_session() as session:
        row = session.execute(build_query(Intent(operation="record", metric="both", date="12-01-2025"))).scalar_one()
        assert (row.actual_volume, row.theoretical_volume, row.support_class) == (26, 26, "C")
        assert session.execute(build_query(Intent(operation="aggregate", metric="actual", aggregate="sum", month=1, year=2025))).scalar_one() == 1153.5
        assert session.execute(build_query(Intent(operation="aggregate", metric="actual", aggregate="max"))).scalar_one() == 75


def test_group_date_range_chainage_and_highest():
    with get_session() as session:
        groups = dict(session.execute(build_query(Intent(operation="group_by_support", metric="actual"))).all())
        assert groups["F"] == 795
        dates = session.execute(build_query(Intent(operation="range_records", metric="actual", start_date="10-01-2025", end_date="12-01-2025"))).scalars().all()
        assert [item.date for item in dates] == ["10-01-2025", "11-01-2025", "12-01-2025"]
        assert session.execute(build_query(Intent(operation="aggregate", metric="actual", aggregate="sum", start_ch=30, end_ch=60))).scalar_one() == 355
        highest = session.execute(build_query(Intent(operation="highest", metric="actual"))).scalar_one()
        assert (highest.date, highest.actual_volume) == ("18-01-2025", 75)


def test_ollama_failure_is_reported(monkeypatch):
    async def fail(*_args):
        raise RuntimeError("Ollama could not classify the question.")

    monkeypatch.setattr("backend.app.main.classify_question", fail)
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"question": "hello"})
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["answer"] == "Ollama could not classify the question."
    assert response.json()["conversation_id"]


@pytest.mark.parametrize("question", ["Good morning", "kaise ho?", "capital of India?"])
def test_non_database_questions_are_chat(question):
    intent = fallback_intent(question)
    if question == "capital of India?":
        assert intent.operation == "out_of_scope"
    else:
        assert intent.operation == "chat"


def test_database_intent_fallbacks():
    record = fallback_intent("01-01-2025 ko actual excavation kitna tha")
    assert record.operation == "record"
    assert (record.date, record.metric) == ("01-01-2025", "actual")

    aggregate = fallback_intent("support class A me total excavation kitna hai")
    assert aggregate.operation == "aggregate"
    assert (aggregate.aggregate, aggregate.support_class) == ("sum", "A")

    highest = fallback_intent("which date had highest excavation")
    assert highest.operation == "highest"


def test_chat_response_has_no_table(monkeypatch):
    async def chat_intent(*_args):
        return Intent(operation="chat")

    async def reply(*_args):
        return "Good morning! How can I help?"

    monkeypatch.setattr("backend.app.main.classify_question", chat_intent)
    monkeypatch.setattr("backend.app.main.chat_reply", reply)
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"question": "Good morning"})
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["answer"] == "Good morning! How can I help?"
    assert "table" not in response.json()


class FakeOllamaResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": self.content, "thinking": "ignored reasoning"}}


class FakeOllamaClient:
    response_content = ""
    last_timeout = None
    last_payload = None

    def __init__(self, timeout):
        type(self).last_timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, _url, json):
        type(self).last_payload = json
        return FakeOllamaResponse(type(self).response_content)


def test_chat_reply_strips_thinking(monkeypatch):
    FakeOllamaClient.response_content = "<think>reasoning</think>Hello!"
    monkeypatch.setattr("backend.app.ollama.httpx.AsyncClient", FakeOllamaClient)
    assert asyncio.run(chat_reply("hello")) == "Hello!"
    assert FakeOllamaClient.last_timeout == 120
    assert FakeOllamaClient.last_payload["think"] is False
    assert FakeOllamaClient.last_payload["options"] == {"temperature": 0.7, "num_predict": 400}


def test_chat_reply_unclosed_thinking_uses_fallback(monkeypatch):
    FakeOllamaClient.response_content = "<think>reasoning..."
    monkeypatch.setattr("backend.app.ollama.httpx.AsyncClient", FakeOllamaClient)
    assert asyncio.run(chat_reply("hello")) == "Sorry, I had trouble answering that question. Please try again."


def test_live_data_question_is_chat_and_prompt_disclaims_live_data():
    intent = asyncio.run(classify_question("bikaner se delhi ki saari train"))
    assert intent.operation == "out_of_scope"


def test_out_of_scope_reply_does_not_call_chat(monkeypatch):
    async def classify(*_args):
        return Intent(operation="out_of_scope")

    async def should_not_run(*_args):
        raise AssertionError("chat_reply must not run for out_of_scope")

    monkeypatch.setattr("backend.app.main.classify_question", classify)
    monkeypatch.setattr("backend.app.main.chat_reply", should_not_run)
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"question": "who is PM of india?"})
    assert response.json()["answer"] == OUT_OF_SCOPE_REPLY
    assert response.json()["table"] == []


@pytest.mark.parametrize("question", ["who is PM of india?", "write a hello world code for html file", "bikaner to delhi train"])
def test_off_topic_fallbacks_are_out_of_scope(question):
    assert fallback_intent(question).operation == "out_of_scope"


def test_tunnel_support_question_is_not_out_of_scope():
    assert fallback_intent("tunnel ka support class A kya hota hai") is None


def test_conversation_persists_turns_and_history(monkeypatch):
    seen_history = []

    async def chat_intent(*_args):
        return Intent(operation="chat")

    async def reply(question, history):
        seen_history.append(history)
        return f"reply to {question}"

    monkeypatch.setattr("backend.app.main.classify_question", chat_intent)
    monkeypatch.setattr("backend.app.main.chat_reply", reply)
    with TestClient(app) as client:
        first = client.post("/api/chat", json={"question": "Hello"}).json()
        second = client.post("/api/chat", json={"question": "How are you?", "conversation_id": first["conversation_id"]}).json()
        listed = client.get("/api/conversations").json()
        messages = client.get(f"/api/conversations/{first['conversation_id']}/messages").json()
    assert first["conversation_id"] == second["conversation_id"]
    assert [item["role"] for item in messages] == ["user", "assistant", "user", "assistant"]
    assert seen_history[1][0]["content"] == "Hello"
    assert messages[0]["content"] == "Hello"
    assert next(item["title"] for item in listed if item["id"] == first["conversation_id"]) == "Hello"


def test_follow_up_reuses_data_intent():
    first = fallback_intent("01-01-2025 ko actual excavation kitna tha")
    follow_up = fallback_intent("aur theoretical?", first)
    assert follow_up.operation == "record"
    assert follow_up.date == "01-01-2025"
    assert follow_up.metric == "theoretical"


def test_unknown_conversation_is_404():
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"question": "hello", "conversation_id": 999999999})
    assert response.status_code == 404


def test_delete_conversation_cascades_messages(monkeypatch):
    async def chat_intent(*_args):
        return Intent(operation="chat")

    async def reply(*_args):
        return "hello"

    monkeypatch.setattr("backend.app.main.classify_question", chat_intent)
    monkeypatch.setattr("backend.app.main.chat_reply", reply)
    with TestClient(app) as client:
        created = client.post("/api/chat", json={"question": "delete me"}).json()
        conversation_id = created["conversation_id"]
        assert client.delete(f"/api/conversations/{conversation_id}").status_code == 204
    with get_session() as session:
        assert session.get(Conversation, conversation_id) is None
        assert session.query(Message).filter(Message.conversation_id == conversation_id).count() == 0
