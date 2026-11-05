from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    conversation_id: int | None = None


class ChatResponse(BaseModel):
    success: bool
    answer: str
    table: list[list[str]] | None = None
    conversation_id: int | None = None


class ConversationTitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class Intent(BaseModel):
    operation: Literal["chat", "out_of_scope", "record", "aggregate", "group_by_support", "range_records", "difference", "highest", "day_records"]
    metric: Literal["actual", "theoretical", "both"] | None = None
    date: str | None = None
    day: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    month: int | None = None
    year: int | None = None
    support_class: str | None = None
    start_ch: float | None = None
    end_ch: float | None = None
    aggregate: Literal["sum", "avg", "min", "max"] | None = None

