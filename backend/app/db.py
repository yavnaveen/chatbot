from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from backend.data.seed_data import SEED_RECORDS

BASE_DIR = Path(__file__).resolve().parents[1]
DATABASE_PATH = BASE_DIR / "data" / "excavation.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Base(DeclarativeBase):
    pass


class ExcavationRecord(Base):
    __tablename__ = "excavation_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(String(10), nullable=False, unique=True, index=True)
    start_ch: Mapped[float] = mapped_column(Float, nullable=False)
    end_ch: Mapped[float] = mapped_column(Float, nullable=False)
    pull: Mapped[float] = mapped_column(Float, nullable=False)
    support_class: Mapped[str] = mapped_column(String(1), nullable=False, index=True)
    theoretical_volume: Mapped[float] = mapped_column(Float, nullable=False)
    actual_volume: Mapped[float] = mapped_column(Float, nullable=False)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    rows_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


def initialize_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as session:
        count = session.scalar(select(func.count()).select_from(ExcavationRecord)) or 0
        if count == 0:
            session.add_all(
                [
                    ExcavationRecord(
                        date=date,
                        start_ch=start_ch,
                        end_ch=end_ch,
                        pull=pull,
                        support_class=support_class,
                        theoretical_volume=theoretical,
                        actual_volume=actual,
                    )
                    for date, start_ch, end_ch, pull, support_class, theoretical, actual in SEED_RECORDS
                ]
            )
        elif count != len(SEED_RECORDS):
            raise RuntimeError(
                f"Database integrity check failed: expected {len(SEED_RECORDS)} records, found {count}."
            )

    with SessionLocal() as session:
        final_count = session.scalar(select(func.count()).select_from(ExcavationRecord)) or 0
        if final_count != len(SEED_RECORDS):
            raise RuntimeError(f"Database seeding failed: expected 56 records, found {final_count}.")


def get_session() -> Session:
    return SessionLocal()

