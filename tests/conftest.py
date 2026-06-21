"""Test fixtures and database isolation.

CRITICAL: the suite must NEVER touch the production database. The session
fixture calls create_all/drop_all, so it MUST run against a dedicated test
database. We derive a test URL from TEST_DATABASE_URL, or by appending
``_test`` to the production database name, and create that database if it does
not exist. A guard fixture asserts we are not pointed at the prod URL.
"""
import os
from collections.abc import Generator
from contextlib import contextmanager

import psycopg2
import pytest
from pytest import MonkeyPatch
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import showcat.ingest.events.models  # noqa: F401

# Import all models so Base.metadata.create_all picks up Phase 1, 2 and 3 tables
import showcat.ingest.history.models  # noqa: F401
import showcat.outputs.playlist.models  # noqa: F401
import showcat.resolve.models  # noqa: F401
import showcat.score.models  # noqa: F401
from showcat.core.database import DATABASE_URL as PROD_DATABASE_URL
from showcat.core.database import Base


def _derive_test_url() -> str:
    """Return the test database URL — explicit override or prod name + '_test'."""
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        return override
    url = make_url(PROD_DATABASE_URL)
    db_name = (url.database or "opener_dev")
    if not db_name.endswith("_test"):
        db_name = f"{db_name}_test"
    # render_as_string(hide_password=False): str(url) masks the password as '***'.
    return url.set(database=db_name).render_as_string(hide_password=False)


TEST_DATABASE_URL = _derive_test_url()


def _ensure_test_database_exists(test_url: str) -> None:
    """CREATE DATABASE the test DB if missing (connect via the server's 'postgres' db)."""
    url = make_url(test_url)
    admin_url = url.set(database="postgres")
    conn = psycopg2.connect(
        host=admin_url.host,
        port=admin_url.port,
        user=admin_url.username,
        password=admin_url.password,
        dbname="postgres",
    )
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (url.database,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        conn.close()


_ensure_test_database_exists(TEST_DATABASE_URL)

# The test engine is bound to the dedicated test DB — never to prod.
engine = create_engine(TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def guard_not_prod_db() -> None:
    """Hard stop: refuse to run if the test engine somehow points at prod."""
    assert str(engine.url) != str(make_url(PROD_DATABASE_URL)), (
        "Test engine is pointed at the PRODUCTION database — aborting to avoid "
        "create_all/drop_all destroying real data."
    )
    assert (engine.url.database or "").endswith("_test"), (
        f"Test database name {engine.url.database!r} must end with '_test'."
    )


@pytest.fixture(scope="session", autouse=True)
def setup_db(guard_not_prod_db: None) -> Generator[None, None, None]:
    """Ensure database tables exist for the testing session (on the TEST db)."""
    Base.metadata.create_all(bind=engine)
    yield
    # Drop tables after test run to leave a clean test DB
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
    monkeypatch.setattr("showcat.core.database.get_db_session", mock_session_generator)
    monkeypatch.setattr("showcat.core.base.get_db_session", mock_session_generator)
    # Stage modules that import get_db_session directly
    monkeypatch.setattr("showcat.ingest.history.backfill.get_db_session", mock_session_generator)
