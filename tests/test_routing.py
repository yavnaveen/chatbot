import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from backend.app.config import API_SECRET_KEY
from backend.app.db import ExcavationRecord, get_session, initialize_database
from backend.app.main import app
from backend.app.router import (
    GREETING_REPLY,
    MONTH_CLARIFICATION_REPLY,
    OUT_OF_SCOPE_REPLY,
    route,
)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    initialize_database()


def get_client() -> TestClient:
    return TestClient(app, headers={"X-API-Key": API_SECRET_KEY})


# ==============================================================================
# Task 1 Router Tests
# ==============================================================================

@pytest.mark.parametrize(
    "greeting",
    [
        "hi",
        "hello",
        "hey",
        "hii",
        "namaste",
        "Good morning",
        "good afternoon",
        "good evening",
        "good night",
        "how are you?",
        "kaise ho",
        "thanks",
        "thank you",
        "shukriya",
        "bye",
        "who are you",
        "what can you do",
        "tum kaun ho",
        "aap kaun ho",
    ],
)
def test_router_greetings(greeting):
    assert route(greeting) == "chat"


@pytest.mark.parametrize(
    "out_query",
    [
        "who is the prime mister of india",
        "capital of france",
        "write python code to reverse a string",
        "aaj mausam kaisa hai",
        "tell me a joke",
        "what is 25 * 4",
        "who won the world cup",
        "what is the weather today",
    ],
)
def test_router_out_of_scope(out_query):
    assert route(out_query) == "out_of_scope"


@pytest.mark.parametrize(
    "data_query",
    [
        "01-01-2025 ko actual excavation kitna tha",
        "total theoretical excavation in February",
        "support class B me total excavation kitna hai",
        "which date had highest excavation",
        "give me data 1 to 5",
        "1to5",
        "1-5",
        "1 se 5",
        "excavation data for support class A",
        "what was the pull on 12/01/2025",
    ],
)
def test_router_data_queries(data_query):
    assert route(data_query) == "data"


def test_router_context_followup():
    assert route("aur theoretical?", has_context=True) == "data"
    assert route("ab class B ke liye", has_context=True) == "data"
    assert route("2", has_context=True) == "data"
    assert route("both", has_context=True) == "data"
    assert route("january", has_context=True) == "data"
    # Long message without context is not follow-up
    assert route("aur theoretical?", has_context=False) == "data"  # contains theoretical


# ==============================================================================
# Task 2 & 3 Endpoint Tests
# ==============================================================================

def test_out_of_scope_reply_endpoint():
    with get_client() as client:
        res = client.post("/api/chat", json={"question": "who is the prime mister of india"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["answer"] == OUT_OF_SCOPE_REPLY
    assert data["table"] == [] or data["table"] is None


def test_ambiguous_day_range_clarification_flow():
    with get_client() as client:
        # 1. Fresh conversation: ambiguous range -> clarification question, no DB query
        res1 = client.post("/api/chat", json={"question": "give me data 1 to 5"})
        assert res1.status_code == 200
        d1 = res1.json()
        assert d1["success"] is True
        assert d1["answer"] == MONTH_CLARIFICATION_REPLY
        assert d1.get("table") is None
        cid = d1["conversation_id"]

        # 2. Reply '2' -> Feb 1-5 data, pending cleared
        res2 = client.post("/api/chat", json={"question": "2", "conversation_id": cid})
        assert res2.status_code == 200
        d2 = res2.json()
        assert d2["success"] is True
        assert d2.get("table") is not None
        rows = d2["table"][1:]
        assert len(rows) == 5
        dates = [r[0] for r in rows]
        assert dates == ["01-02-2025", "02-02-2025", "03-02-2025", "04-02-2025", "05-02-2025"]


def test_ambiguous_day_range_reply_first_5_rows():
    with get_client() as client:
        # 1. Ambiguous range -> clarification question
        res1 = client.post("/api/chat", json={"question": "give me data 1-5"})
        assert res1.status_code == 200
        d1 = res1.json()
        assert d1.get("table") is None
        cid = d1["conversation_id"]

        # 2. Reply 'first 5 rows' -> rows with id 1-5
        res2 = client.post("/api/chat", json={"question": "first 5 rows", "conversation_id": cid})
        assert res2.status_code == 200
        d2 = res2.json()
        assert d2["success"] is True
        assert d2.get("table") is not None
        rows = d2["table"][1:]
        assert len(rows) == 5
        ids = [int(r[0]) for r in rows]
        assert ids == [1, 2, 3, 4, 5]


def test_direct_question_with_month():
    with get_client() as client:
        # "give me data 1 to 5 january" -> returns Jan 1-5 data directly without clarification
        res = client.post("/api/chat", json={"question": "give me data 1 to 5 january"})
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data.get("table") is not None
        rows = data["table"][1:]
        assert len(rows) == 5
        dates = [r[0] for r in rows]
        assert dates == ["01-01-2025", "02-01-2025", "03-01-2025", "04-01-2025", "05-01-2025"]


def test_context_reuse_month_with_note():
    with get_client() as client:
        # 1. Ask about February
        res1 = client.post("/api/chat", json={"question": "total theoretical excavation in February"})
        assert res1.status_code == 200
        cid = res1.json()["conversation_id"]

        # 2. Ask "give me data 1 to 5" -> returns Feb 1-5 with previous question note
        res2 = client.post("/api/chat", json={"question": "give me data 1 to 5", "conversation_id": cid})
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["success"] is True
        assert "Showing 1 to 5 February 2025 (based on your previous question)." in data2["answer"]
        rows = data2.get("table", [])[1:]
        assert len(rows) == 5
        assert all("02-2025" in r[0] for r in rows)


# ==============================================================================
# Task 4 Safety Tests
# ==============================================================================

@pytest.mark.parametrize(
    "bad_statement",
    [
        "drop table excavation_records",
        "delete from excavation_records",
        "update excavation_records set pull = 999",
    ],
)
def test_safety_mutation_refusal(bad_statement):
    with get_session() as session:
        initial_count = session.scalar(select(func.count()).select_from(ExcavationRecord))

    with get_client() as client:
        res = client.post("/api/chat", json={"question": bad_statement})
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "read-only assistant" in data["answer"]
        assert "cannot delete, modify, or change" in data["answer"]

    with get_session() as session:
        final_count = session.scalar(select(func.count()).select_from(ExcavationRecord))
        assert final_count == initial_count
