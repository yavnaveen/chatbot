from contextlib import asynccontextmanager
import logging
import re
import time
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Select, func, select, text

from backend.app.audit import log_audit_event
from backend.app.config import CORS_ORIGINS, OLLAMA_MODEL
from backend.app.conversation_service import (
    add_message,
    create_conversation,
    get_conversation,
    last_data_intent,
    message_payload,
    recent_history,
    title_from_question,
    utc_now,
)
from backend.app.db import Conversation, ExcavationRecord, get_session, initialize_database
from backend.app.formatters import _number, record_answer
from backend.app.importer import import_excavation_data
from backend.app.ollama import (
    MUTATION_REFUSAL_REPLY,
    OUT_OF_SCOPE_REPLY,
    chat_reply,
    check_ollama_health,
    classify_question,
    extract_dates_from_text,
    fallback_intent,
    generate_sql_or_chat,
    validate_safe_read_query,
)
from backend.app.query_builder import build_query
from backend.app.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationTitleUpdate,
    Intent,
    PublicChatRequest,
    PublicChatResponse,
)
from backend.app.security import rate_limit_dependency, verify_api_key


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    logging.info("Ollama model configured: %s", OLLAMA_MODEL)
    print(f"Ollama model configured: {OLLAMA_MODEL}")
    yield


app = FastAPI(
    title="Tunnel Excavation AI API",
    description="Offline & Cloudflare Tunnel-ready AI Chatbot API powered by qwen2.5-coder:7b",
    version="2.1.0",
    lifespan=lifespan,
)

# CORS configuration for Cloudflare Tunnel and external frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False if "*" in CORS_ORIGINS else True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)


@app.get("/", tags=["System"])
def root_index() -> dict[str, object]:
    """Root index providing API information and documentation links."""
    return {
        "service": "Tunnel Excavation AI API",
        "model": OLLAMA_MODEL,
        "status": "online",
        "docs": "/docs",
        "health": "/health",
        "chat_endpoint": "POST /chat",
    }


@app.get("/health", tags=["System"])
async def health_check() -> dict[str, object]:
    """Health check endpoint to verify database connectivity and Ollama model reachability."""
    db_status = "connected"
    db_records = 0
    db_error = None

    try:
        with get_session() as session:
            count = session.scalar(select(func.count()).select_from(ExcavationRecord))
            db_records = count if count is not None else 0
    except Exception as exc:
        db_status = "error"
        db_error = str(exc)

    ollama_info = await check_ollama_health()
    is_healthy = (db_status == "connected") and ollama_info.get("reachable", False)

    return {
        "status": "healthy" if is_healthy else "degraded",
        "database": {
            "status": db_status,
            "records": db_records,
            "error": db_error,
        },
        "ollama": {
            "status": "connected" if ollama_info.get("reachable") else "disconnected",
            "model": ollama_info.get("configured_model", OLLAMA_MODEL),
            "model_available": ollama_info.get("model_available", False),
            "installed_models": ollama_info.get("installed_models", []),
            "error": ollama_info.get("error"),
        },
    }


@app.get("/api/health", tags=["System"])
async def api_health() -> dict[str, object]:
    """Legacy health check for existing frontend compatibility."""
    with get_session() as session:
        count = session.scalar(select(func.count()).select_from(ExcavationRecord)) or 0
    ollama_info = await check_ollama_health()
    return {
        "ok": count >= 56,
        "records": count,
        "ollama_reachable": ollama_info.get("reachable", False),
        "model_available": ollama_info.get("model_available", False),
    }


def format_sql_result(query: str, columns: list[str], rows: list) -> tuple[str, list[list[str]] | None]:
    """Format raw SQL execution results into a human-readable summary and table."""
    if not rows:
        return "No excavation records matched that question.", None

    table = [columns]
    table.extend([[str(cell) if cell is not None else "" for cell in row] for row in rows])

    # Single scalar aggregate result (e.g. SELECT SUM(actual_volume)...)
    if len(rows) == 1 and len(columns) == 1:
        val = rows[0][0]
        col = columns[0]
        val_str = _number(val) if isinstance(val, (int, float)) else str(val)
        return f"Result ({col}): {val_str}", table

    # Single excavation record
    if len(rows) == 1:
        row_dict = dict(zip(columns, rows[0]))
        date_val = row_dict.get("date")
        act_val = row_dict.get("actual_volume")
        theo_val = row_dict.get("theoretical_volume")
        pull_val = row_dict.get("pull")
        sc_val = row_dict.get("support_class")
        if act_val is not None and theo_val is not None and date_val is not None and pull_val is not None:
            return (
                f"On {date_val}, pull was {_number(pull_val)}, actual excavation was {_number(act_val)} "
                f"and theoretical excavation was {_number(theo_val)}. Support class was {sc_val}.",
                table,
            )
        parts = [f"{col}: {_number(val) if isinstance(val, (int, float)) else val}" for col, val in row_dict.items()]
        return "; ".join(parts), table

    if len(rows) > 1 and "date" in columns:
        date_idx = columns.index("date")
        months = {str(r[date_idx])[3:5] for r in rows if len(str(r[date_idx])) >= 5}
        if len(months) > 1:
            month_map = {"01": "January", "02": "February"}
            m_labels = " & ".join(month_map.get(m, m) for m in sorted(list(months)))
            return (
                f"Found {len(rows)} record(s) matching your query across {m_labels}. "
                f"(Tip: You can specify a month like '1 to 5 Feb' or '1 to 5 Jan' to filter).",
                table,
            )

    return f"Found {len(rows)} record(s) matching your query.", table


async def execute_chat(
    question: str,
    conversation_id: Optional[int] = None,
    client_ip: str = "unknown",
) -> tuple[bool, str, list[list[str]] | None, int, str | None]:
    """Core excavation chatbot reasoning pipeline with conversation memory and Text-to-SQL."""
    start_time = time.perf_counter()
    with get_session() as session:
        conversation = get_conversation(session, conversation_id) if conversation_id else None
        if conversation_id and conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if conversation is None:
            conversation = create_conversation(session)

        history = recent_history(session, conversation.id, 10)
        previous_intent = last_data_intent(session, conversation.id)
        if conversation.title == "New chat" and not history:
            conversation.title = title_from_question(question)
        user_message = add_message(session, conversation, "user", question)

        def finish(
            success: bool,
            answer: str,
            table: list[list[str]] | None = None,
            intent: Intent | None = None,
            generated_query: str | None = None,
        ) -> tuple[bool, str, list[list[str]] | None, int, str | None]:
            add_message(
                session,
                conversation,
                "assistant",
                answer,
                rows=table,
                intent=intent,
                generated_query=generated_query,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            is_violation = intent is not None and intent.operation == "mutation_refusal"
            log_audit_event(
                client_ip=client_ip,
                endpoint="/chat",
                question=question,
                generated_query=generated_query,
                response_time_ms=elapsed_ms,
                status="success" if success else "error",
                violation_flag=is_violation,
            )
            return success, answer, table, conversation.id, generated_query

        # Pre-check 1: Resolve pending clarification from previous turn
        if previous_intent and previous_intent.operation == "pending_clarification":
            ans_clean = question.strip().lower()
            d1 = previous_intent.start_day or 1
            d2 = previous_intent.end_day or 5

            # Match option 1 (January)
            if (
                ans_clean in {"1", "jan", "january", "1.", "option 1"}
                or re.search(r"\b(?:jan|january)\b", ans_clean)
                or ans_clean.startswith("1")
            ) and not any(w in ans_clean for w in ("row", "record", "id", "first", "pehle")):
                start_date = f"{d1:02d}-01-2025"
                end_date = f"{d2:02d}-01-2025"
                resolved_intent = Intent(
                    operation="range_records",
                    metric="both",
                    start_date=start_date,
                    end_date=end_date,
                    month=1,
                    year=2025,
                )
                statement = build_query(resolved_intent)
                compiled_sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
                records = [r[0] for r in session.execute(statement).all()]
                table = [["Date", "Pull", "Support Class", "Theoretical", "Actual"]]
                table.extend([[r.date, _number(r.pull), r.support_class, _number(r.theoretical_volume), _number(r.actual_volume)] for r in records])
                return finish(True, f"Showing {d1} to {d2} January 2025:", table, resolved_intent, compiled_sql)

            # Match option 2 (February)
            if (
                ans_clean in {"2", "feb", "february", "2.", "option 2"}
                or re.search(r"\b(?:feb|february)\b", ans_clean)
                or ans_clean.startswith("2")
            ):
                start_date = f"{d1:02d}-02-2025"
                end_date = f"{d2:02d}-02-2025"
                resolved_intent = Intent(
                    operation="range_records",
                    metric="both",
                    start_date=start_date,
                    end_date=end_date,
                    month=2,
                    year=2025,
                )
                statement = build_query(resolved_intent)
                compiled_sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
                records = [r[0] for r in session.execute(statement).all()]
                table = [["Date", "Pull", "Support Class", "Theoretical", "Actual"]]
                table.extend([[r.date, _number(r.pull), r.support_class, _number(r.theoretical_volume), _number(r.actual_volume)] for r in records])
                return finish(True, f"Showing {d1} to {d2} February 2025:", table, resolved_intent, compiled_sql)

            # Match option 3 (Both Months / dono)
            if (
                ans_clean in {"3", "both", "dono", "all", "3.", "option 3"}
                or "both" in ans_clean
                or "dono" in ans_clean
                or ans_clean.startswith("3")
            ):
                resolved_intent = Intent(
                    operation="day_range",
                    metric="both",
                    start_day=d1,
                    end_day=d2,
                    year=2025,
                )
                statement = build_query(resolved_intent)
                compiled_sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
                records = [r[0] for r in session.execute(statement).all()]
                table = [["Date", "Pull", "Support Class", "Theoretical", "Actual"]]
                table.extend([[r.date, _number(r.pull), r.support_class, _number(r.theoretical_volume), _number(r.actual_volume)] for r in records])
                return finish(True, f"Showing days {d1} to {d2} across January & February 2025:", table, resolved_intent, compiled_sql)

            # Match option 4 / "first 5 rows" / row / record / id
            if (
                ans_clean in {"4", "4.", "option 4"}
                or any(w in ans_clean for w in ("first", "top", "row", "record", "id", "pehle", "pehli"))
            ):
                stmt = select(ExcavationRecord).where(ExcavationRecord.id.between(d1, d2)).order_by(ExcavationRecord.id.asc())
                compiled_sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
                records = [r[0] for r in session.execute(stmt).all()]
                table = [["ID", "Date", "Pull", "Support Class", "Theoretical", "Actual"]]
                table.extend([[str(r.id), r.date, _number(r.pull), r.support_class, _number(r.theoretical_volume), _number(r.actual_volume)] for r in records])
                resolved_intent = Intent(operation="range_records", metric="both", start_day=d1, end_day=d2)
                return finish(True, f"Showing first {len(records)} record(s) by ID (ID {d1} to {d2}):", table, resolved_intent, compiled_sql)

        # Pre-check 2: Ambiguous day range pre-check BEFORE classify_question
        range_match = re.search(
            r"(?<!\d)(\d{1,2})\s*(?:to|-|se|tak|and)\s*(\d{1,2})(?!\d)",
            question,
            re.IGNORECASE,
        )
        if range_match:
            d1 = int(range_match.group(1))
            d2 = int(range_match.group(2))
            if 1 <= d1 <= 31 and 1 <= d2 <= 31 and d1 <= d2:
                q_lower = question.lower()
                month_names = (
                    "january", "jan", "february", "feb", "march", "mar", "april", "apr",
                    "may", "june", "jun", "july", "jul", "august", "aug", "september", "sep",
                    "october", "oct", "november", "nov", "december", "dec"
                )
                has_month_name = any(re.search(rf"\b{m}\b", q_lower) for m in month_names)
                has_full_date = bool(extract_dates_from_text(question))
                has_row_words = any(
                    re.search(rf"\b{w}\b", q_lower)
                    for w in ("row", "rows", "record", "records", "id", "ids", "first", "top", "pehle", "pehli", "limit")
                )

                # If there's an explicit month name in question (e.g. "give me data 1 to 5 january")
                if has_month_name and not has_row_words:
                    month_num = 1 if re.search(r"\b(?:jan|january)\b", q_lower) else 2
                    m_label = "January" if month_num == 1 else "February"
                    start_date = f"{d1:02d}-{month_num:02d}-2025"
                    end_date = f"{d2:02d}-{month_num:02d}-2025"
                    direct_intent = Intent(
                        operation="range_records",
                        metric="both",
                        start_date=start_date,
                        end_date=end_date,
                        month=month_num,
                        year=2025,
                    )
                    statement = build_query(direct_intent)
                    compiled_sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
                    records = [r[0] for r in session.execute(statement).all()]
                    table = [["Date", "Pull", "Support Class", "Theoretical", "Actual"]]
                    table.extend([[r.date, _number(r.pull), r.support_class, _number(r.theoretical_volume), _number(r.actual_volume)] for r in records])
                    return finish(True, f"Showing {d1} to {d2} {m_label} 2025:", table, direct_intent, compiled_sql)

                # If no month name, no full date, no row/record/id/first/top words:
                if not has_month_name and not has_full_date and not has_row_words:
                    # Check if conversation has a previous data intent with a month or date
                    prev_month = None
                    prev_year = 2025
                    if previous_intent and previous_intent.operation != "pending_clarification":
                        if previous_intent.month:
                            prev_month = previous_intent.month
                            prev_year = previous_intent.year or 2025
                        elif previous_intent.date and len(previous_intent.date) >= 10:
                            try:
                                prev_month = int(previous_intent.date[3:5])
                                prev_year = int(previous_intent.date[6:10])
                            except ValueError:
                                pass
                        elif previous_intent.start_date and len(previous_intent.start_date) >= 10:
                            try:
                                prev_month = int(previous_intent.start_date[3:5])
                                prev_year = int(previous_intent.start_date[6:10])
                            except ValueError:
                                pass

                    if prev_month is not None:
                        # Reuse previous month and add the note:
                        # "Showing 1 to 5 <Month> <Year> (based on your previous question)."
                        m_label = {1: "January", 2: "February"}.get(prev_month, f"Month {prev_month}")
                        start_date = f"{d1:02d}-{prev_month:02d}-{prev_year}"
                        end_date = f"{d2:02d}-{prev_month:02d}-{prev_year}"
                        reused_intent = Intent(
                            operation="range_records",
                            metric="both",
                            start_date=start_date,
                            end_date=end_date,
                            month=prev_month,
                            year=prev_year,
                        )
                        statement = build_query(reused_intent)
                        compiled_sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
                        records = [r[0] for r in session.execute(statement).all()]
                        table = [["Date", "Pull", "Support Class", "Theoretical", "Actual"]]
                        table.extend([[r.date, _number(r.pull), r.support_class, _number(r.theoretical_volume), _number(r.actual_volume)] for r in records])
                        note = f"Showing {d1} to {d2} {m_label} {prev_year} (based on your previous question)."
                        return finish(True, note, table, reused_intent, compiled_sql)

                    # Otherwise, NO month in context, NO month in query:
                    # do NOT run any query. Reply asking: which month (January / February / Both), or do they want first N rows.
                    clarification_msg = (
                        f"Kaunse month ka {d1} to {d2} data chahiye?\n\n"
                        f"1. January ({d1:02d}-01-2025 to {d2:02d}-01-2025)\n"
                        f"2. February ({d1:02d}-02-2025 to {d2:02d}-02-2025)\n"
                        f"3. Both Months (January & February dono)\n"
                        f"4. First {d2} rows (Table ke pehle {d2} records by ID)\n\n"
                        f"Kripya option number (1, 2, 3, 4) ya month name (Jan / Feb / Both / First {d2} rows) batayein."
                    )
                    pending_intent = Intent(
                        operation="pending_clarification",
                        start_day=d1,
                        end_day=d2,
                    )
                    user_message.intent_json = pending_intent.model_dump_json()
                    session.commit()
                    return finish(True, clarification_msg, table=None, intent=pending_intent, generated_query=None)

        # Step 1: Classify intent or handle conversational / out-of-scope / mutation queries
        try:
            intent = await classify_question(question, previous_intent, history[-4:])
        except Exception as exc:
            return finish(False, str(exc), generated_query=None)

        if intent.operation == "mutation_refusal":
            user_message.intent_json = intent.model_dump_json()
            session.commit()
            return finish(True, MUTATION_REFUSAL_REPLY, table=None, intent=intent, generated_query=None)
        if intent.operation == "out_of_scope":
            user_message.intent_json = intent.model_dump_json()
            session.commit()
            return finish(True, OUT_OF_SCOPE_REPLY, table=[], intent=intent, generated_query=None)
        if intent.operation == "chat":
            answer = await chat_reply(question, history)
            return finish(True, answer, intent=None, generated_query=None)

        # Step 2: Attempt zero-shot Text-to-SQL generation using qwen2.5-coder:7b
        # If intent already has verified specific date or day range parameters, execute verified query builder directly for 100% precision
        has_verified_range = (
            (intent.operation == "range_records" and intent.start_date and intent.end_date)
            or (intent.operation == "day_range" and intent.start_day and intent.end_day)
        )
        if not has_verified_range:
            try:
                category, content = await generate_sql_or_chat(question, history)
                if category == "mutation_refusal":
                    return finish(True, MUTATION_REFUSAL_REPLY, table=None, intent=Intent(operation="mutation_refusal"), generated_query=None)
                if category == "out_of_scope":
                    return finish(True, OUT_OF_SCOPE_REPLY, table=[], intent=Intent(operation="out_of_scope"), generated_query=None)
                if category == "sql":
                    validate_safe_read_query(content)
                    res = session.execute(text(content))
                    cols = list(res.keys())
                    rows = res.fetchall()
                    answer, tbl = format_sql_result(content, cols, rows)
                    return finish(True, answer, table=tbl, intent=intent, generated_query=content)
            except ValueError as exc:
                if "Security violation" in str(exc):
                    return finish(True, MUTATION_REFUSAL_REPLY, table=None, intent=Intent(operation="mutation_refusal"), generated_query=None)
                logging.info("Text-to-SQL pipeline triggered fallback: %s", exc)
            except Exception as exc:
                logging.info("Text-to-SQL pipeline triggered fallback: %s", exc)

        # Step 3: Verified query builder fallback pipeline
        try:
            if intent.operation == "record" and not intent.date:
                return finish(False, "Please specify a date in DD-MM-YYYY format.", intent=intent, generated_query=None)
            if intent.operation == "aggregate" and intent.aggregate is None:
                return finish(False, "Please clarify whether you want a total, average, minimum, or maximum.", intent=intent, generated_query=None)

            statement = build_query(intent)
            if not isinstance(statement, Select):
                raise ValueError("Security violation: Only SELECT queries are permitted.")

            compiled_sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
            rows = session.execute(statement).all()

            if intent.operation == "row_count":
                count_val = rows[0][0]
                return finish(True, f"The excavation database contains {_number(count_val)} records.", table=None, intent=intent, generated_query=compiled_sql)

            if intent.operation in {"record", "range_records", "day_records", "day_range"}:
                records = [row[0] for row in rows]
                if not records:
                    return finish(True, "No excavation records matched that question.", intent=intent, generated_query=compiled_sql)
                if intent.operation == "record":
                    item = records[0]
                    table = [
                        ["Date", "Pull", "Support Class", "Theoretical", "Actual"],
                        [item.date, _number(item.pull), item.support_class, _number(item.theoretical_volume), _number(item.actual_volume)],
                    ]
                    return finish(True, record_answer(item, intent.metric), table, intent, generated_query=compiled_sql)
                if intent.operation == "day_records":
                    answer = "; ".join(f"On {item.date}, pull was {_number(item.pull)} and support class was {item.support_class}." for item in records)
                    table = [["Date", "Pull", "Support Class"]]
                    table.extend([[item.date, _number(item.pull), item.support_class] for item in records])
                    return finish(True, answer, table, intent, generated_query=compiled_sql)
                if intent.operation == "day_range":
                    month_map = {"01": "January", "02": "February"}
                    months_present = sorted(list({rec.date[3:5] for rec in records}))
                    m_names = " & ".join(month_map.get(m, m) for m in months_present)
                    answer = (
                        f"Found {len(records)} excavation record(s) for days {intent.start_day} to {intent.end_day} "
                        f"across all available months ({m_names}). "
                        f"(Tip: Specify a month like '1 to 5 Feb' or '1 to 5 Jan' to filter)."
                    )
                    table = [["Date", "Pull", "Support Class", "Theoretical", "Actual"]]
                    table.extend([
                        [
                            item.date,
                            _number(item.pull),
                            item.support_class,
                            _number(item.theoretical_volume),
                            _number(item.actual_volume),
                        ]
                        for item in records
                    ])
                    return finish(True, answer, table, intent, generated_query=compiled_sql)
                if len(records) == 1:
                    answer = record_answer(records[0], intent.metric)
                else:
                    date_range_str = f" from {records[0].date} to {records[-1].date}" if records else ""
                    context_note = ""
                    if intent.month and not extract_dates_from_text(question):
                        month_name = {1: "January", 2: "February"}.get(intent.month, f"Month {intent.month}")
                        context_note = f" (auto-resolved from previous {month_name} context)"
                    answer = f"Found {len(records)} excavation record(s){date_range_str}{context_note}:"
                table = [["Date", "Pull", "Support Class", "Theoretical", "Actual"]]
                table.extend([
                    [
                        item.date,
                        _number(item.pull),
                        item.support_class,
                        _number(item.theoretical_volume),
                        _number(item.actual_volume),
                    ]
                    for item in records
                ])
                return finish(True, answer, table, intent, generated_query=compiled_sql)

            if intent.operation == "highest":
                if not rows:
                    return finish(True, "No excavation records matched that question.", intent=intent, generated_query=compiled_sql)
                record = rows[0][0]
                return finish(True, f"The highest actual excavation was {_number(record.actual_volume)} on {record.date}.", intent=intent, generated_query=compiled_sql)

            if intent.operation == "group_by_support":
                if not rows:
                    return finish(True, "No excavation records matched that question.", intent=intent, generated_query=compiled_sql)
                if intent.metric == "both":
                    answer = "; ".join(
                        f"Support class {support}: {_number(actual or 0)} actual, {_number(theoretical or 0)} theoretical excavation"
                        for support, theoretical, actual in rows
                    )
                    table = [["Support Class", "Actual Excavation", "Theoretical Excavation"]]
                    table.extend([[support, _number(actual or 0), _number(theoretical or 0)] for support, theoretical, actual in rows])
                else:
                    metric_name = "theoretical" if intent.metric == "theoretical" else "actual"
                    answer = "; ".join(f"Support class {support}: {_number(total or 0)} {metric_name} excavation" for support, total in rows)
                    table = [["Support Class", f"{metric_name.title()} Excavation"]]
                    table.extend([[support, _number(total or 0)] for support, total in rows])
                return finish(True, answer + ".", table, intent, generated_query=compiled_sql)

            if intent.operation == "difference":
                theoretical, actual = rows[0]
                difference = (actual or 0) - (theoretical or 0)
                answer = f"Theoretical excavation was {_number(theoretical or 0)}, actual excavation was {_number(actual or 0)}, so actual minus theoretical was {_number(difference)}."
                return finish(True, answer, intent=intent, generated_query=compiled_sql)

            if intent.metric == "both":
                theoretical, actual = rows[0]
                label = {"sum": "Total", "avg": "Average", "min": "Minimum", "max": "Maximum"}[intent.aggregate or "sum"]
                answer = f"{label} actual excavation was {_number(actual or 0)} and {label.lower()} theoretical excavation was {_number(theoretical or 0)}."
                return finish(True, answer, intent=intent, generated_query=compiled_sql)

            value = rows[0][0]
            if value is None:
                return finish(True, "No excavation records matched that question.", intent=intent, generated_query=compiled_sql)
            label = {"sum": "Total", "avg": "Average", "min": "Minimum", "max": "Maximum"}[intent.aggregate or "sum"]
            metric = "theoretical" if intent.metric == "theoretical" else "actual"
            return finish(True, f"{label} {metric} excavation was {_number(value)}.", intent=intent, generated_query=compiled_sql)

        except RuntimeError as exc:
            return finish(False, str(exc), generated_query=None)
        except (ValueError, TypeError) as exc:
            return finish(False, f"I could not safely understand that question: {exc}", generated_query=None)


@app.post(
    "/chat",
    response_model=PublicChatResponse,
    response_model_exclude_none=True,
    dependencies=[Depends(verify_api_key), Depends(rate_limit_dependency)],
    tags=["Chat"],
)
async def public_chat(payload: PublicChatRequest, request: Request) -> PublicChatResponse:
    """Public chat endpoint accepting JSON {"message": "user question"} and returning {"response": "formatted answer", "generated_query": "...", "status": "success"}."""
    client_ip = request.headers.get("CF-Connecting-IP") or (request.client.host if request.client else "unknown")
    success, answer, table, conversation_id, generated_query = await execute_chat(
        question=payload.query_text,
        conversation_id=payload.conversation_id,
        client_ip=client_ip,
    )
    return PublicChatResponse(
        response=answer,
        generated_query=generated_query,
        status="success" if success else "error",
        conversation_id=conversation_id,
        table=table,
    )


@app.post(
    "/api/chat",
    response_model=ChatResponse,
    response_model_exclude_none=True,
    dependencies=[Depends(verify_api_key), Depends(rate_limit_dependency)],
    tags=["Chat"],
)
async def api_chat_with_memory(payload: ChatRequest, request: Request) -> ChatResponse:
    """Internal / frontend chat endpoint with conversation memory."""
    client_ip = request.headers.get("CF-Connecting-IP") or (request.client.host if request.client else "unknown")
    success, answer, table, conversation_id, generated_query = await execute_chat(
        question=payload.question,
        conversation_id=payload.conversation_id,
        client_ip=client_ip,
    )
    return ChatResponse(
        success=success,
        answer=answer,
        table=table,
        conversation_id=conversation_id,
        generated_query=generated_query,
    )


@app.post(
    "/api/upload",
    dependencies=[Depends(verify_api_key), Depends(rate_limit_dependency)],
    tags=["Data"],
)
@app.post(
    "/upload",
    dependencies=[Depends(verify_api_key), Depends(rate_limit_dependency)],
    tags=["Data"],
)
async def upload_excavation_data(
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, object]:
    """Upload CSV or Excel (.xlsx) file containing excavation records to update or insert into the database."""
    start_time = time.perf_counter()
    client_ip = request.headers.get("CF-Connecting-IP") or (request.client.host if request.client else "unknown")
    filename = file.filename or "unknown.csv"

    if not filename.lower().endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only .csv and .xlsx files are supported.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        with get_session() as session:
            result = import_excavation_data(file_bytes, filename, session)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            log_audit_event(
                client_ip=client_ip,
                endpoint="/api/upload",
                question=f"Uploaded file: {filename}",
                response_time_ms=elapsed_ms,
                status="success",
                metadata={"filename": filename, "imported": result["imported"], "total": result["total_records"]},
            )
            return result
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        log_audit_event(
            client_ip=client_ip,
            endpoint="/api/upload",
            question=f"Uploaded file: {filename}",
            response_time_ms=elapsed_ms,
            status="error",
            violation_flag=False,
            metadata={"error": str(exc)},
        )
        raise HTTPException(status_code=400, detail=f"Failed to process file: {exc}")


@app.post("/api/conversations", dependencies=[Depends(verify_api_key)], tags=["Conversations"])
def new_conversation() -> dict[str, object]:
    with get_session() as session:
        conversation = create_conversation(session)
        return {"id": conversation.id, "title": conversation.title}


@app.get("/api/conversations", dependencies=[Depends(verify_api_key)], tags=["Conversations"])
def list_conversations() -> list[dict[str, object]]:
    with get_session() as session:
        conversations = session.query(Conversation).order_by(Conversation.updated_at.desc()).all()
        return [{"id": item.id, "title": item.title, "updated_at": item.updated_at.isoformat()} for item in conversations]


@app.get("/api/conversations/{conversation_id}/messages", dependencies=[Depends(verify_api_key)], tags=["Conversations"])
def conversation_messages(conversation_id: int) -> list[dict[str, object]]:
    with get_session() as session:
        conversation = get_conversation(session, conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return [message_payload(message) for message in conversation.messages]


@app.patch("/api/conversations/{conversation_id}", dependencies=[Depends(verify_api_key)], tags=["Conversations"])
def rename_conversation(conversation_id: int, update: ConversationTitleUpdate) -> dict[str, object]:
    with get_session() as session:
        conversation = get_conversation(session, conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation.title = update.title.strip()
        conversation.updated_at = utc_now()
        session.commit()
        return {"id": conversation.id, "title": conversation.title}


@app.delete("/api/conversations/{conversation_id}", status_code=204, dependencies=[Depends(verify_api_key)], tags=["Conversations"])
def delete_conversation(conversation_id: int) -> None:
    with get_session() as session:
        conversation = get_conversation(session, conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        session.delete(conversation)
        session.commit()
