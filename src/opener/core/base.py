import abc
import json
import traceback
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from opener.core.database import DeadLetter, RunLedger, get_db_session
from opener.core.logging import get_logger

logger = get_logger("opener.core.base")


class BaseStage(abc.ABC):
    """Abstract base class that all pipeline stages must inherit.

    Enforces:
    1. Connection/transaction scoping through the database.
    2. Automated logging and run ledger recording.
    3. Containment of errors in the dead_letter table (preventing pipeline crashes).
    4. The idempotency contract: re-running a stage must produce no side-effects/duplication.
    """

    @property
    @abc.abstractmethod
    def stage_name(self) -> str:
        """The unique name identifying this stage (e.g. 'ingest/history')."""
        pass

    def run(self, *args: Any, **kwargs: Any) -> RunLedger:
        """Wrapper method orchestrating the stage execution lifecycle."""
        logger.info(
            "Stage execution started",
            extra={"stage_name": self.stage_name, "stage_args": args, "stage_kwargs": kwargs},
        )

        # 1. Initialize run ledger entry
        try:
            with get_db_session() as session:
                run_record = RunLedger(
                    stage_name=self.stage_name,
                    status="started",
                    started_at=datetime.now(UTC),
                    run_metadata=kwargs if kwargs else None,
                )
                session.add(run_record)
                session.commit()
                session.refresh(run_record)
                run_id = run_record.id
        except Exception as db_err:
            logger.critical(
                "Failed to initialize run ledger",
                extra={"stage_name": self.stage_name, "error": str(db_err)},
            )
            raise db_err

        # 2. Run actual stage work in its own database session (transactional isolation)
        try:
            records_processed = 0
            with get_db_session() as session:
                records_processed = self._run(session, *args, **kwargs)

            # 3. Update run ledger to completed on success
            with get_db_session() as session:
                run_record = session.query(RunLedger).filter_by(id=run_id).one()
                run_record.status = "completed"
                run_record.ended_at = datetime.now(UTC)
                run_record.records_processed = records_processed
                session.commit()
                session.refresh(run_record)

            logger.info(
                "Stage execution completed successfully",
                extra={
                    "stage_name": self.stage_name,
                    "run_id": run_id,
                    "records_processed": records_processed,
                },
            )
            return run_record

        except Exception as stage_err:
            tb = traceback.format_exc()
            logger.error(
                "Stage execution failed",
                extra={
                    "stage_name": self.stage_name,
                    "run_id": run_id,
                    "error": str(stage_err),
                },
                exc_info=True,
            )

            # 4. Contain errors inside dead_letter and mark ledger as failed
            try:
                # Format raw kwargs as text/json safely
                try:
                    raw_content = json.dumps({"args": args, "kwargs": kwargs})
                except Exception:
                    raw_content = str({"args": args, "kwargs": kwargs})

                with get_db_session() as session:
                    # Write to dead letter
                    dead_letter_record = DeadLetter(
                        stage_name=self.stage_name,
                        record_id=str(kwargs.get("record_id")) if kwargs.get("record_id") else None,
                        raw_content=raw_content,
                        error_message=str(stage_err),
                        occurred_at=datetime.now(UTC),
                        stack_trace=tb,
                    )
                    session.add(dead_letter_record)

                    # Update run ledger status
                    run_record = session.query(RunLedger).filter_by(id=run_id).one()
                    run_record.status = "failed"
                    run_record.ended_at = datetime.now(UTC)
                    run_record.error_message = str(stage_err)
                    session.commit()
                    session.refresh(run_record)

                return run_record

            except Exception as telemetry_err:
                logger.critical(
                    "Failed to record execution failure to database",
                    extra={
                        "stage_name": self.stage_name,
                        "run_id": run_id,
                        "telemetry_error": str(telemetry_err),
                        "original_error": str(stage_err),
                    },
                )
                raise stage_err from None

    @abc.abstractmethod
    def _run(self, session: Session, *args: Any, **kwargs: Any) -> int:
        """The method containing stage-specific execution logic.

        Must return the count of records successfully processed.
        Should be implemented by subclasses following strict idempotency guidelines:
        - Must operate inside the provided DB session.
        - Must not create duplicate or orphan records if run multiple times.
        - Must raise exceptions for any unhandled failures to trigger dead_letter routing.
        """
        pass
