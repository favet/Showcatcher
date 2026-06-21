import os
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/opener_dev"
)

# Create the SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Configure the sessionmaker
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative Base for models using modern SQLAlchemy 2.0 class declarations
class Base(DeclarativeBase):
    pass


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ORM Models

class RunLedger(Base):
    __tablename__ = "run_ledger"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stage_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class DeadLetter(Base):
    __tablename__ = "dead_letter"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stage_name: Mapped[str] = mapped_column(String(100), nullable=False)
    record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
