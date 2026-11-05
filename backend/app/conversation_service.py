import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db import Conversation, Message
from backend.app.schemas import Intent


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_conversation(session: Session, title: str = "New chat") -> Conversation:
    conversation = Conversation(title=title, created_at=utc_now(), updated_at=utc_now())
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def get_conversation(session: Session, conversation_id: int) -> Conversation | None:
    return session.get(Conversation, conversation_id)


def recent_history(session: Session, conversation_id: int, limit: int) -> list[dict[str, str]]:
    messages = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()
    history = []
    for message in reversed(messages):
        if message.intent_json:
            try:
                if Intent.model_validate_json(message.intent_json).operation == "out_of_scope":
                    continue
            except ValueError:
                pass
        history.append({"role": message.role, "content": message.content[:1000]})
    return history


def last_data_intent(session: Session, conversation_id: int) -> Intent | None:
    message = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.intent_json.is_not(None))
        .order_by(Message.id.desc())
        .limit(1)
    ).first()
    if not message or not message.intent_json:
        return None
    try:
        intent = Intent.model_validate_json(message.intent_json)
        return None if intent.operation in {"chat", "out_of_scope"} else intent
    except ValueError:
        return None


def add_message(
    session: Session,
    conversation: Conversation,
    role: str,
    content: str,
    rows: list[list[str]] | None = None,
    intent: Intent | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation.id,
        role=role,
        content=content,
        rows_json=json.dumps(rows, ensure_ascii=False) if rows is not None else None,
        intent_json=intent.model_dump_json() if intent and intent.operation != "chat" else None,
        created_at=utc_now(),
    )
    session.add(message)
    conversation.updated_at = utc_now()
    session.add(conversation)
    session.commit()
    session.refresh(message)
    return message


def title_from_question(question: str) -> str:
    title = " ".join(question.strip().split())[:40]
    return title or "New chat"


def message_payload(message: Message) -> dict[str, object]:
    rows = json.loads(message.rows_json) if message.rows_json else []
    return {
        "role": message.role,
        "content": message.content,
        "rows": rows,
        "created_at": message.created_at.isoformat(),
    }
