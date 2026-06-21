from collections.abc import Generator
from contextlib import contextmanager

import pytest
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import opener.ingest.events.models  # noqa: F401

# Import all models so Base.metadata.create_all picks up Phase 1 and 2 tables
import opener.ingest.history.models  # noqa: F401
from opener.core.database import DATABASE_URL, Base

# Connect to the test DB
engine = create_engine(DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_db() -> Generator[None, None, None]:
    """Ensure database tables exist for the testing session."""
    Base.metadata.create_all(bind=engine)
    yield
    # Drop tables after test run to leave a clean DB
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provides a transactional database session that rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def mock_get_db_session(monkeypatch: MonkeyPatch, db_session: Session) -> None:
    """Monkeypatch get_db_session context manager to return the transactional session."""

    @contextmanager
    def mock_session_generator() -> Generator[Session, None, None]:
        yield db_session

    # Core framework
    monkeypatch.setattr("opener.core.database.get_db_session", mock_session_generator)
    monkeypatch.setattr("opener.core.base.get_db_session", mock_session_generator)
    # Stage modules that import get_db_session directly
    monkeypatch.setattr("opener.ingest.history.backfill.get_db_session", mock_session_generator)

