from contextlib import asynccontextmanager
import logging
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Select, func, select, text

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
from backend.app.ollama import (
    MUTATION_REFUSAL_REPLY,
    OUT_OF_SCOPE_REPLY,
    chat_reply,
    check_ollama_health,
    classify_question,
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
        "ok": count == 56,
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

    return f"Found {len(rows)} record(s) matching your query.", table


async def execute_chat(
    question: str,
    conversation_id: Optional[int] = None,
) -> tuple[bool, str, list[list[str]] | None, int, str | None]:
    """Core excavation chatbot reasoning pipeline with conversation memory and Text-to-SQL."""
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
            add_message(session, conversation, "assistant", answer, rows=table, intent=intent)
            return success, answer, table, conversation.id, generated_query

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

            if intent.operation in {"record", "range_records", "day_records"}:
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
                answer = "; ".join(record_answer(item, intent.metric) for item in records)
                table = [["Date", "Support Class", "Theoretical", "Actual"]]
                table.extend([[item.date, item.support_class, _number(item.theoretical_volume), _number(item.actual_volume)] for item in records])
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
async def public_chat(request: PublicChatRequest) -> PublicChatResponse:
    """Public chat endpoint accepting JSON {"message": "user question"} and returning {"response": "formatted answer", "generated_query": "...", "status": "success"}."""
    success, answer, table, conversation_id, generated_query = await execute_chat(
        question=request.query_text,
        conversation_id=request.conversation_id,
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
async def api_chat_with_memory(request: ChatRequest) -> ChatResponse:
    """Internal / frontend chat endpoint with conversation memory."""
    success, answer, table, conversation_id, generated_query = await execute_chat(
        question=request.question,
        conversation_id=request.conversation_id,
    )
    return ChatResponse(
        success=success,
        answer=answer,
        table=table,
        conversation_id=conversation_id,
        generated_query=generated_query,
    )


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
