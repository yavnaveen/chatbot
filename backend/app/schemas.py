from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None


class ChatResponse(BaseModel):
    success: bool
    answer: str
    table: list[list[str]] | None = None
    conversation_id: int | None = None
    generated_query: str | None = None


class PublicChatRequest(BaseModel):
    message: Optional[str] = Field(default=None, max_length=2000)
    question: Optional[str] = Field(default=None, max_length=2000)
    conversation_id: Optional[int] = None

    @model_validator(mode="after")
    def validate_message_present(self):
        text = self.message or self.question
        if not text or not text.strip():
            raise ValueError("Field 'message' or 'question' is required.")
        return self

    @property
    def query_text(self) -> str:
        return (self.message or self.question or "").strip()


class PublicChatResponse(BaseModel):
    response: str
    generated_query: Optional[str] = None
    status: Literal["success", "error"] = "success"
    conversation_id: Optional[int] = None
    table: Optional[list[list[str]]] = None


class ConversationTitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class Intent(BaseModel):
    operation: Literal[
        "chat",
        "out_of_scope",
        "record",
        "aggregate",
        "group_by_support",
        "range_records",
        "difference",
        "highest",
        "day_records",
        "day_range",
        "row_count",
        "mutation_refusal",
    ]
    metric: Literal["actual", "theoretical", "both"] | None = None
    date: str | None = None
    day: int | None = None
    start_day: int | None = None
    end_day: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    month: int | None = None
    year: int | None = None
    support_class: str | None = None
    start_ch: float | None = None
    end_ch: float | None = None
    aggregate: Literal["sum", "avg", "min", "max"] | None = None
