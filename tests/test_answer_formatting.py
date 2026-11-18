import pytest
from fastapi.testclient import TestClient

from backend.app.config import API_SECRET_KEY
from backend.app.db import ExcavationRecord, get_session, initialize_database
from backend.app.formatters import build_result_table
from backend.app.main import app


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


def test_range_difference_answer_and_table():
    with get_client() as client:
        res = client.post(
            "/api/chat",
            json={"question": "difference between theoretical and actual excavation from 01-01-2025 to 05-01-2025"},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    ans = data["answer"]
    assert "From 01-01-2025 to 05-01-2025 (5 records)" in ans
    assert "123.5" in ans
    assert "132.5" in ans
    assert "+9" in ans
    assert "(actual is higher)" in ans

    # table with 5 rows plus a Total row (plus header row = 7 rows total)
    table = data["table"]
    assert table is not None
    assert len(table) == 7
    assert table[0] == ["Date", "Pull", "Support Class", "Theoretical", "Actual", "Difference"]
    # Total row
    total_row = table[-1]
    assert total_row[0] == "Total"
    assert total_row[3] == "123.5"
    assert total_row[4] == "132.5"
    assert total_row[5] == "+9"


def test_whole_dataset_difference():
    with get_session() as session:
        from backend.app.formatters import get_dataset_bounds
        first_d, last_d, _ = get_dataset_bounds(session)

    with get_client() as client:
        res = client.post(
            "/api/chat",
            json={"question": "difference between actual and theoretical across all records 2025"},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    ans = data["answer"]
    assert "Across all records" in ans
    assert first_d in ans
    assert last_d in ans
    assert "Theoretical: 2019.5" in ans
    assert "Actual: 2219" in ans
    assert "+199.5" in ans


def test_single_date_answer_and_badge_record():
    with get_client() as client:
        res = client.post(
            "/api/chat",
            json={"question": "What was the actual excavation on 07-02-2025?"},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    ans = data["answer"]
    assert "On 07-02-2025:" in ans
    assert "1 records" not in ans
    table = data["table"]
    assert table is not None
    assert len(table) == 2
    assert table[1][0] == "07-02-2025"


def test_month_total_scope_text_and_table():
    with get_client() as client:
        res = client.post(
            "/api/chat",
            json={"question": "total actual excavation in February 2025"},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    ans = data["answer"]
    assert "In February 2025" in ans
    assert "1065.5" in ans
    # Rule 6: Single-number answers: text only, no table. can_show_rows: true
    assert data.get("table") is None
    assert data.get("can_show_rows") is True


def test_year_not_typed_assumptions():
    with get_client() as client:
        res = client.post(
            "/api/chat",
            json={"question": "total excavation in February"},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "assumptions" in data
    assert any("Assumed year 2025" in a for a in data["assumptions"])


def test_zero_matching_records_no_table():
    with get_client() as client:
        res = client.post(
            "/api/chat",
            json={"question": "total actual excavation for support class A in February 2025"},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    ans = data["answer"]
    assert "No records found" in ans
    assert "Available data: 01-01-2025 to" in ans
    assert data.get("table") is None


def test_more_than_200_matching_rows_truncation():
    mock_records = [
        ExcavationRecord(
            id=i,
            date="01-01-2025",
            start_ch=1.0,
            end_ch=2.0,
            pull=1.0,
            support_class="A",
            theoretical_volume=10.0,
            actual_volume=12.0,
        )
        for i in range(1, 251)
    ]
    display_tbl, all_tbl, is_trunc = build_result_table(mock_records, is_difference=False, max_display=200)
    assert is_trunc is True
    assert len(display_tbl) == 201
    assert len(all_tbl) == 251

    diff_display, diff_all, diff_trunc = build_result_table(mock_records, is_difference=True, max_display=200)
    assert diff_trunc is True
    assert len(diff_display) == 202  # header + 200 data + Total
    assert len(diff_all) == 252  # header + 250 data + Total
