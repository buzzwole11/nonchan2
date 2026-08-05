"""Shared test fixtures.

Unit tests need nothing but the package. Integration and E2E tests need PostgreSQL; when
it is unavailable they skip with a message that says how to start one, rather than failing
in a way that looks like a code defect.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "fixtures"

DEFAULT_TEST_DB = "postgresql+psycopg://papermatch:papermatch@127.0.0.1:5432/papermatch_test"
TEST_DATABASE_URL = os.environ.get("PAPERMATCH_TEST_DATABASE_URL", DEFAULT_TEST_DB)

# Set before any application module reads settings.
os.environ.setdefault("PAPERMATCH_ENVIRONMENT", "test")
os.environ["PAPERMATCH_DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("PAPERMATCH_FIXTURES_DIR", str(FIXTURES_DIR))


def _database_available() -> bool:
    try:
        engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
    except SQLAlchemyError:
        return False
    return True


DB_AVAILABLE = _database_available()

requires_db = pytest.mark.skipif(
    not DB_AVAILABLE,
    reason=(
        f"PostgreSQL not reachable at {TEST_DATABASE_URL}. "
        "Start one with `docker compose up -d db` and run `make db-test-setup`."
    ),
)


@pytest.fixture(scope="session")
def engine():  # type: ignore[no-untyped-def]
    if not DB_AVAILABLE:
        pytest.skip("database unavailable")
    from papermatch_api.models import Base

    engine = create_engine(TEST_DATABASE_URL)
    # `create_all` cannot create an extension, and the `embeddings` table has a `vector`
    # column (migration 0009). Done here so the schema the tests build matches the one
    # Alembic builds.
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    # The schema under test is the one Alembic produces; tests assert on it in
    # test_migrations.py. Here we create it directly so a test run does not depend on
    # migration ordering.
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine) -> Iterator[Session]:  # type: ignore[no-untyped-def]
    """A session wrapped in a transaction that is rolled back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(engine, db_session: Session) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    """A TestClient whose requests run inside the test's transaction."""
    from papermatch_api.db import get_db
    from papermatch_api.main import create_app

    app = create_app()

    def override_get_db() -> Iterator[Session]:
        yield db_session
        db_session.flush()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_db(db_session: Session) -> Session:
    """A database containing the field taxonomy and the sample corpus."""
    from papermatch_api.providers.base import PaperQuery
    from papermatch_api.providers.mock_paper import MockPaperProvider
    from papermatch_api.services.ingestion import ingest, load_fields

    load_fields(db_session, FIXTURES_DIR)
    ingest(db_session, MockPaperProvider(FIXTURES_DIR), query=PaperQuery(limit=100))
    db_session.flush()
    return db_session
