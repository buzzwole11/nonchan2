"""The migrations and the models must describe the same schema.

A schema that only exists as SQLAlchemy models is a schema nobody can deploy. This runs
the real migration chain against a scratch database and asserts that Alembic sees nothing
left to generate — which is what "safe migrations" means in practice (spec section 0).
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from papermatch_api.models import Base
from tests.conftest import TEST_DATABASE_URL, requires_db

pytestmark = [pytest.mark.integration, requires_db]

MIGRATION_DB_URL = f"{TEST_DATABASE_URL}_migrations"


def _alembic_config(url: str) -> Config:
    from pathlib import Path

    api_root = Path(__file__).resolve().parents[1]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "alembic"))
    # env.py reads this in preference to application settings, so the scratch database is
    # targeted without mutating (and having to un-mutate) global configuration.
    config.attributes["db_url"] = url
    return config


@pytest.fixture(scope="module")
def migrated_engine():  # type: ignore[no-untyped-def]
    """A database built purely by running the migrations."""
    admin = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    db_name = MIGRATION_DB_URL.rsplit("/", 1)[-1]
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        connection.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin.dispose()

    engine = None
    try:
        command.upgrade(_alembic_config(MIGRATION_DB_URL), "head")
        engine = create_engine(MIGRATION_DB_URL)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        admin = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin.dispose()


def test_migrations_create_every_table_the_models_declare(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import inspect

    tables = set(inspect(migrated_engine).get_table_names())
    expected = set(Base.metadata.tables)
    assert expected <= tables, f"migrations are missing: {sorted(expected - tables)}"


def test_no_schema_drift_between_models_and_migrations(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    with migrated_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    assert diff == [], (
        "models and migrations disagree. Run "
        "`uv run alembic revision --autogenerate -m '<change>'` and review the result."
    )


def test_the_database_is_stamped_at_the_head_revision(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    """Compared against the script directory rather than a hardcoded id, so adding a
    migration does not require editing this test."""
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(_alembic_config(MIGRATION_DB_URL)).get_current_head()
    with migrated_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == head


def test_downgrade_to_base_leaves_no_application_tables(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    """A migration that cannot be rolled back is not a safe migration."""
    from sqlalchemy import inspect

    config = _alembic_config(MIGRATION_DB_URL)
    command.downgrade(config, "base")
    remaining = set(inspect(migrated_engine).get_table_names()) - {"alembic_version"}
    assert remaining == set(), f"downgrade left tables behind: {sorted(remaining)}"
    command.upgrade(config, "head")
