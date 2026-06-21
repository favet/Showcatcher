from typing import Any
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from opener.core.base import BaseStage
from opener.core.database import Base, DeadLetter

# Define a temporary testing database model using modern Mapped classes
class DummyModel(Base):
    __tablename__ = "dummy_model"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    value: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class DummySuccessStage(BaseStage):
    @property
    def stage_name(self) -> str:
        return "test/success"

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        session.add(DummyModel(value="success_value"))
        return 1


class DummyFailStage(BaseStage):
    @property
    def stage_name(self) -> str:
        return "test/fail"

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        raise ValueError("Simulated stage error")


class DummyIdempotentStage(BaseStage):
    @property
    def stage_name(self) -> str:
        return "test/idempotency"

    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:  # noqa: ARG002
        existing = session.query(DummyModel).filter_by(value="idempotent_value").first()
        if not existing:
            session.add(DummyModel(value="idempotent_value"))
            return 1
        return 0


def test_stage_success(db_session: Session) -> None:
    """Verifies that a successful stage records status completed and commits updates."""
    # Run the stage
    stage = DummySuccessStage()
    run_record = stage.run()

    # Assert ledger outcomes
    assert run_record.status == "completed"
    assert run_record.stage_name == "test/success"
    assert run_record.records_processed == 1
    assert run_record.ended_at is not None
    assert run_record.error_message is None

    # Assert DB writes actually committed
    records = db_session.query(DummyModel).all()
    assert len(records) == 1
    assert records[0].value == "success_value"


def test_stage_failure(db_session: Session) -> None:
    """Verifies that failures are written to dead_letter without raising a crash."""
    stage = DummyFailStage()
    run_record = stage.run(record_id="rec-999", sample="payload")

    # Assert ledger captured failure
    assert run_record.status == "failed"
    assert run_record.error_message == "Simulated stage error"

    # Assert dead letter capturing
    dead_letters = db_session.query(DeadLetter).all()
    assert len(dead_letters) == 1
    assert dead_letters[0].stage_name == "test/fail"
    assert dead_letters[0].record_id == "rec-999"
    assert "Simulated stage error" in dead_letters[0].error_message
    assert dead_letters[0].stack_trace is not None


def test_stage_idempotency(db_session: Session) -> None:
    """Verifies that re-running a stage has no duplicative side effects."""
    stage = DummyIdempotentStage()

    # First run
    run1 = stage.run()
    assert run1.status == "completed"
    assert run1.records_processed == 1

    records_first = db_session.query(DummyModel).filter_by(value="idempotent_value").all()
    assert len(records_first) == 1

    # Second run
    run2 = stage.run()
    assert run2.status == "completed"
    assert run2.records_processed == 0

    # Ensure no duplicates
    records_second = db_session.query(DummyModel).filter_by(value="idempotent_value").all()
    assert len(records_second) == 1
