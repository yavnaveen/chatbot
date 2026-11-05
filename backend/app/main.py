from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

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
from backend.app.ollama import OUT_OF_SCOPE_REPLY, OLLAMA_MODEL, chat_reply, classify_question
from backend.app.query_builder import build_query
from backend.app.schemas import ChatRequest, ChatResponse, ConversationTitleUpdate, Intent


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    logging.info("Ollama model configured: %s", OLLAMA_MODEL)
    print(f"Ollama model: {OLLAMA_MODEL}")
    yield


app = FastAPI(title="Tunnel Excavation AI", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["POST", "GET", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, object]:
    with get_session() as session:
        count = session.scalar(select(func.count()).select_from(ExcavationRecord)) or 0
    return {"ok": count == 56, "records": count}


@app.post("/api/conversations")
def new_conversation() -> dict[str, object]:
    with get_session() as session:
        conversation = create_conversation(session)
        return {"id": conversation.id, "title": conversation.title}


@app.get("/api/conversations")
def list_conversations() -> list[dict[str, object]]:
    with get_session() as session:
        conversations = session.query(Conversation).order_by(Conversation.updated_at.desc()).all()
        return [{"id": item.id, "title": item.title, "updated_at": item.updated_at.isoformat()} for item in conversations]


@app.get("/api/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: int) -> list[dict[str, object]]:
    with get_session() as session:
        if not get_conversation(session, conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation = get_conversation(session, conversation_id)
        return [message_payload(message) for message in conversation.messages]


@app.patch("/api/conversations/{conversation_id}")
def rename_conversation(conversation_id: int, update: ConversationTitleUpdate) -> dict[str, object]:
    with get_session() as session:
        conversation = get_conversation(session, conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation.title = update.title.strip()
        conversation.updated_at = utc_now()
        session.commit()
        return {"id": conversation.id, "title": conversation.title}


@app.delete("/api/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int) -> None:
    with get_session() as session:
        conversation = get_conversation(session, conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        session.delete(conversation)
        session.commit()


# Retained as a reference for the existing excavation response logic; the route below adds persistence.
async def _legacy_chat(request: ChatRequest) -> ChatResponse:
    try:
        intent = await classify_question(request.question)
        if intent.operation == "chat":
            return ChatResponse(success=True, answer=await chat_reply(request.question), table=None)
        if intent.operation == "record" and not intent.date:
            return ChatResponse(success=False, answer="Please specify a date in DD-MM-YYYY format.")
        if intent.operation == "aggregate" and intent.aggregate is None:
            return ChatResponse(success=False, answer="Please clarify whether you want a total, average, minimum, or maximum.")
        statement = build_query(intent)
        with get_session() as session:
            rows = session.execute(statement).all()
        if intent.operation in {"record", "range_records", "day_records"}:
            records = [row[0] for row in rows]
            if not records:
                return ChatResponse(success=True, answer="No excavation records matched that question.")
            if intent.operation == "record":
                item = records[0]
                table = [["Date", "Pull", "Support Class", "Theoretical", "Actual"], [
                    item.date,
                    _number(item.pull),
                    item.support_class,
                    _number(item.theoretical_volume),
                    _number(item.actual_volume),
                ]]
                return ChatResponse(success=True, answer=record_answer(item, intent.metric), table=table)
            if intent.operation == "day_records":
                answer = "; ".join(f"On {item.date}, pull was {_number(item.pull)} and support class was {item.support_class}." for item in records)
                table = [["Date", "Pull", "Support Class"]]
                table.extend([[item.date, _number(item.pull), item.support_class] for item in records])
                return ChatResponse(success=True, answer=answer, table=table)
            answer = "; ".join(record_answer(item, intent.metric) for item in records)
            table = [["Date", "Support Class", "Theoretical", "Actual"]]
            table.extend([
                [item.date, item.support_class, _number(item.theoretical_volume), _number(item.actual_volume)]
                for item in records
            ])
            return ChatResponse(success=True, answer=answer, table=table)
        if intent.operation == "highest":
            if not rows:
                return ChatResponse(success=True, answer="No excavation records matched that question.")
            record = rows[0][0]
            return ChatResponse(success=True, answer=f"The highest actual excavation was {_number(record.actual_volume)} on {record.date}.")
        if intent.operation == "group_by_support":
            if not rows:
                return ChatResponse(success=True, answer="No excavation records matched that question.")
            if intent.metric == "both":
                answer = "; ".join(f"Support class {support}: {_number(actual or 0)} actual, {_number(theoretical or 0)} theoretical excavation" for support, theoretical, actual in rows)
                table = [["Support Class", "Actual Excavation", "Theoretical Excavation"]]
                table.extend([[support, _number(actual or 0), _number(theoretical or 0)] for support, theoretical, actual in rows])
            else:
                metric_name = "theoretical" if intent.metric == "theoretical" else "actual"
                answer = "; ".join(f"Support class {support}: {_number(total or 0)} {metric_name} excavation" for support, total in rows)
                table = [["Support Class", f"{metric_name.title()} Excavation"]]
                table.extend([[support, _number(total or 0)] for support, total in rows])
            return ChatResponse(success=True, answer=answer + ".", table=table)
        if intent.operation == "difference":
            theoretical, actual = rows[0]
            difference = (actual or 0) - (theoretical or 0)
            return ChatResponse(success=True, answer=f"Theoretical excavation was {_number(theoretical or 0)}, actual excavation was {_number(actual or 0)}, so actual minus theoretical was {_number(difference)}.")
        if intent.metric == "both":
            theoretical, actual = rows[0]
            label = {"sum": "Total", "avg": "Average", "min": "Minimum", "max": "Maximum"}[intent.aggregate or "sum"]
            return ChatResponse(success=True, answer=f"{label} actual excavation was {_number(actual or 0)} and {label.lower()} theoretical excavation was {_number(theoretical or 0)}.")
        value = rows[0][0]
        if value is None:
            return ChatResponse(success=True, answer="No excavation records matched that question.")
        label = {"sum": "Total", "avg": "Average", "min": "Minimum", "max": "Maximum"}[intent.aggregate or "sum"]
        metric = "theoretical" if intent.metric == "theoretical" else "actual"
        return ChatResponse(success=True, answer=f"{label} {metric} excavation was {_number(value)}.")
    except RuntimeError as exc:
        return ChatResponse(success=False, answer=str(exc))
    except (ValueError, TypeError) as exc:
        return ChatResponse(success=False, answer=f"I could not safely understand that question: {exc}")


@app.post("/api/chat", response_model=ChatResponse, response_model_exclude_none=True)
async def chat_with_memory(request: ChatRequest) -> ChatResponse:
    with get_session() as session:
        conversation = get_conversation(session, request.conversation_id) if request.conversation_id else None
        if request.conversation_id and conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if conversation is None:
            conversation = create_conversation(session)
        history = recent_history(session, conversation.id, 10)
        previous_intent = last_data_intent(session, conversation.id)
        if conversation.title == "New chat" and not history:
            conversation.title = title_from_question(request.question)
        user_message = add_message(session, conversation, "user", request.question)

        def finish(success: bool, answer: str, table: list[list[str]] | None = None, intent: Intent | None = None) -> ChatResponse:
            add_message(session, conversation, "assistant", answer, rows=table, intent=intent)
            return ChatResponse(success=success, answer=answer, table=table, conversation_id=conversation.id)

        try:
            intent = await classify_question(request.question, previous_intent, history[-4:])
            if intent.operation == "out_of_scope":
                user_message.intent_json = intent.model_dump_json()
                session.commit()
                return finish(True, OUT_OF_SCOPE_REPLY, table=[], intent=intent)
            if intent.operation == "chat":
                answer = await chat_reply(request.question, history)
                return finish(True, answer, intent=None)
            if intent.operation == "record" and not intent.date:
                return finish(False, "Please specify a date in DD-MM-YYYY format.", intent=intent)
            if intent.operation == "aggregate" and intent.aggregate is None:
                return finish(False, "Please clarify whether you want a total, average, minimum, or maximum.", intent=intent)
            statement = build_query(intent)
            rows = session.execute(statement).all()
            if intent.operation in {"record", "range_records", "day_records"}:
                records = [row[0] for row in rows]
                if not records:
                    return finish(True, "No excavation records matched that question.", intent=intent)
                if intent.operation == "record":
                    item = records[0]
                    table = [["Date", "Pull", "Support Class", "Theoretical", "Actual"], [item.date, _number(item.pull), item.support_class, _number(item.theoretical_volume), _number(item.actual_volume)]]
                    return finish(True, record_answer(item, intent.metric), table, intent)
                if intent.operation == "day_records":
                    answer = "; ".join(f"On {item.date}, pull was {_number(item.pull)} and support class was {item.support_class}." for item in records)
                    table = [["Date", "Pull", "Support Class"]]
                    table.extend([[item.date, _number(item.pull), item.support_class] for item in records])
                    return finish(True, answer, table, intent)
                answer = "; ".join(record_answer(item, intent.metric) for item in records)
                table = [["Date", "Support Class", "Theoretical", "Actual"]]
                table.extend([[item.date, item.support_class, _number(item.theoretical_volume), _number(item.actual_volume)] for item in records])
                return finish(True, answer, table, intent)
            if intent.operation == "highest":
                if not rows:
                    return finish(True, "No excavation records matched that question.", intent=intent)
                record = rows[0][0]
                return finish(True, f"The highest actual excavation was {_number(record.actual_volume)} on {record.date}.", intent=intent)
            if intent.operation == "group_by_support":
                if not rows:
                    return finish(True, "No excavation records matched that question.", intent=intent)
                if intent.metric == "both":
                    answer = "; ".join(f"Support class {support}: {_number(actual or 0)} actual, {_number(theoretical or 0)} theoretical excavation" for support, theoretical, actual in rows)
                    table = [["Support Class", "Actual Excavation", "Theoretical Excavation"]]
                    table.extend([[support, _number(actual or 0), _number(theoretical or 0)] for support, theoretical, actual in rows])
                else:
                    metric_name = "theoretical" if intent.metric == "theoretical" else "actual"
                    answer = "; ".join(f"Support class {support}: {_number(total or 0)} {metric_name} excavation" for support, total in rows)
                    table = [["Support Class", f"{metric_name.title()} Excavation"]]
                    table.extend([[support, _number(total or 0)] for support, total in rows])
                return finish(True, answer + ".", table, intent)
            if intent.operation == "difference":
                theoretical, actual = rows[0]
                difference = (actual or 0) - (theoretical or 0)
                answer = f"Theoretical excavation was {_number(theoretical or 0)}, actual excavation was {_number(actual or 0)}, so actual minus theoretical was {_number(difference)}."
                return finish(True, answer, intent=intent)
            if intent.metric == "both":
                theoretical, actual = rows[0]
                label = {"sum": "Total", "avg": "Average", "min": "Minimum", "max": "Maximum"}[intent.aggregate or "sum"]
                answer = f"{label} actual excavation was {_number(actual or 0)} and {label.lower()} theoretical excavation was {_number(theoretical or 0)}."
                return finish(True, answer, intent=intent)
            value = rows[0][0]
            if value is None:
                return finish(True, "No excavation records matched that question.", intent=intent)
            label = {"sum": "Total", "avg": "Average", "min": "Minimum", "max": "Maximum"}[intent.aggregate or "sum"]
            metric = "theoretical" if intent.metric == "theoretical" else "actual"
            return finish(True, f"{label} {metric} excavation was {_number(value)}.", intent=intent)
        except RuntimeError as exc:
            return finish(False, str(exc))
        except (ValueError, TypeError) as exc:
            return finish(False, f"I could not safely understand that question: {exc}")

