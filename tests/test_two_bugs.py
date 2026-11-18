import pytest
from fastapi.testclient import TestClient

from backend.app.config import API_SECRET_KEY
from backend.app.db import initialize_database
from backend.app.main import app
from backend.app.router import OUT_OF_SCOPE_REPLY


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    initialize_database()


@pytest.fixture(autouse=True)
def mock_ollama_classifier(monkeypatch):
    from backend.app.nlp import pipeline
    from backend.app.nlp.llm import deterministic_classify

    async def mock_classify(raw_question, normalized, entities, context=None, mock=False):
        return deterministic_classify(raw_question, normalized, entities, context)

    monkeypatch.setattr(pipeline, "classify_with_llm", mock_classify)


def get_client() -> TestClient:
    return TestClient(app, headers={"X-API-Key": API_SECRET_KEY})


def test_finance_minister_off_topic_out_of_scope():
    with get_client() as client:
        res = client.post(
            "/api/chat",
            json={"question": "can you give me the name of the finance minister of india?"},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert OUT_OF_SCOPE_REPLY in data["answer"] or "only answer questions related to the tunnel excavation" in data["answer"]
    # Must NOT return table or data dump
    assert data.get("table") in (None, [])


@pytest.mark.parametrize(
    "q",
    [
        "who is the prime mister of india",
        "write html code",
        "tell me a joke",
    ],
)
def test_off_topic_queries_refused(q: str):
    with get_client() as client:
        res = client.post("/api/chat", json={"question": q})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "only answer questions related to the tunnel excavation" in data["answer"]
    assert data.get("table") in (None, [])


def test_minimum_actual_excavation_single_number():
    with get_client() as client:
        res = client.post("/api/chat", json={"question": "minimum actual excavation"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    ans = data["answer"]
    # Text with value and date and support class
    assert "Minimum actual excavation: 5.5" in ans
    assert "01-01-2025" in ans
    assert "support class A" in ans
    # Text only, no table
    assert data.get("table") is None
    # can_show_rows true
    assert data.get("can_show_rows") is True


def test_total_theoretical_excavation_single_number():
    with get_client() as client:
        res = client.post("/api/chat", json={"question": "total theoretical excavation"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    ans = data["answer"]
    assert "Total theoretical excavation: 2019.5" in ans
    # Text only, no table
    assert data.get("table") is None
    assert data.get("can_show_rows") is True


def test_give_me_all_data_table_first_20_rows():
    with get_client() as client:
        res = client.post("/api/chat", json={"question": "give me all data"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    table = data.get("table")
    assert table is not None
    # Header + first 20 rows = 21 rows
    assert len(table) == 21
    # all_rows contains full dataset
    all_rows = data.get("all_rows")
    assert all_rows is not None
    assert len(all_rows) > 21


def test_show_records_for_january():
    with get_client() as client:
        res = client.post("/api/chat", json={"question": "show records for january"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    table = data.get("table")
    assert table is not None
    # First 20 rows of january
    assert len(table) == 21


def test_single_date_data_1_row_table():
    with get_client() as client:
        res = client.post("/api/chat", json={"question": "07-02-2025 ka data"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    table = data.get("table")
    assert table is not None
    # Header + 1 data row = 2 rows
    assert len(table) == 2
    assert table[1][0] == "07-02-2025"


def test_date_range_data_table_5_rows():
    with get_client() as client:
        res = client.post("/api/chat", json={"question": "1 jan to 5 jan data"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    table = data.get("table")
    assert table is not None
    # Header + 5 data rows = 6 rows
    assert len(table) == 6


def test_minimum_alone_clarification():
    with get_client() as client:
        res = client.post("/api/chat", json={"question": "minimum"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    ans = data["answer"]
    # No topic evidence -> Clarification, not a data dump!
    assert "Did you mean:" in ans
    assert data.get("table") is None


def test_minimun_actaul_excavtion_typos():
    with get_client() as client:
        res = client.post("/api/chat", json={"question": "minimun actaul excavtion"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    ans = data["answer"]
    assert "Minimum actual excavation: 5.5" in ans
    assert "01-01-2025" in ans
    assert data.get("table") is None
    assert data.get("can_show_rows") is True
