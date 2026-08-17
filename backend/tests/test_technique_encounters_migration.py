"""
Round-trip test for migrations/versions/0039_technique_encounters.py
(Technique Dossier — PR #31 review finding: the general suite builds its
schema via `Base.metadata.create_all` (tests/conftest.py), not via
`alembic upgrade`, so 0039's own upgrade()/downgrade() were never actually
executed by any test. Same gap `test_scenario_notification_matrix_migration.py`
closed for 0038 after the identical finding on PR #25.

Same "stamp-then-step" pattern as that file and test_cmmc_tenancy_migration.py:
build the "as of 0038" baseline directly from the current ORM models minus
the one new table 0039 introduces, stamp Alembic to 0038 without running
anything, then upgrade to 0039 in isolation — exercising exactly what 0039's
own upgrade()/downgrade() do, not the rest of the migration history.
"""
import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.session import Base
import app.models  # noqa: F401 — ensure every model (incl. TechniqueEncounter) is registered

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TARGET_REVISION = "0039_technique_encounters"
_PRIOR_REVISION = "0038_scenario_notification_matrix"

_NEW_TABLE = "technique_encounters"
_EXPECTED_INDEXES = {"ix_technique_encounters_user_id", "ix_technique_encounters_technique_id"}
_EXPECTED_COLUMNS = {
    "id", "user_id", "technique_id", "encounter_count",
    "first_encountered_at", "last_encountered_at",
}


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg


def _pre_0039_metadata() -> sa.MetaData:
    """Every current ORM table except `technique_encounters` — reproducing
    the schema exactly as it existed at 0038, since `Base.metadata` (built
    from the current model) already has the table 0039 introduces."""
    baseline = sa.MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name == _NEW_TABLE:
            continue
        table.to_metadata(baseline)
    return baseline


@pytest.fixture
def migration_engine(tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'technique_encounters_migration.db'}"
    engine = create_engine(sqlite_url)
    _pre_0039_metadata().create_all(engine)
    cfg = _alembic_config(sqlite_url)

    original_sync_url = settings.SYNC_DATABASE_URL
    settings.SYNC_DATABASE_URL = sqlite_url
    try:
        command.stamp(cfg, _PRIOR_REVISION)
        yield engine, cfg
    finally:
        settings.SYNC_DATABASE_URL = original_sync_url
        engine.dispose()


def _insert_user(conn, user_id: str) -> None:
    conn.execute(
        text("""
            INSERT INTO users (id, email, hashed_password, full_name, role, is_active, created_at, updated_at)
            VALUES (:id, :email, 'x', 'Test User', 'analyst', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )


def test_upgrade_creates_technique_encounters_table_with_indexes_and_unique_constraint(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert _NEW_TABLE in tables

        columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({_NEW_TABLE})"))}
        assert columns == _EXPECTED_COLUMNS

        index_names = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
        assert _EXPECTED_INDEXES.issubset(index_names)

        # SQLite folds a named table-level UNIQUE constraint into an
        # autoindex rather than surfacing it under its own name in
        # sqlite_master's index rows — same reason test_cmmc_tenancy_
        # migration.py's partial unique indexes were asserted via a
        # dedicated op.create_index call instead. The constraint's name
        # does survive verbatim in the table's own stored DDL, so assert
        # it there.
        table_sql = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"),
            {"name": _NEW_TABLE},
        ).scalar()
        assert "uq_technique_encounter_user_technique" in table_sql


def test_upgrade_then_unique_constraint_rejects_duplicate_user_technique_pair(migration_engine):
    """Proves the constraint the migration actually ships is load-bearing,
    not just present by name — same discipline as test_cmmc_tenancy_
    migration.py's raw-SQL CHECK constraint test."""
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        _insert_user(conn, "u-1")
        conn.execute(text(
            "INSERT INTO technique_encounters (id, user_id, technique_id, encounter_count, "
            "first_encountered_at, last_encountered_at) "
            "VALUES ('te-1', 'u-1', 'T1078', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO technique_encounters (id, user_id, technique_id, encounter_count, "
                "first_encountered_at, last_encountered_at) "
                "VALUES ('te-2', 'u-1', 'T1078', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))


def test_downgrade_drops_table_and_indexes_cleanly(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)
    with engine.connect() as conn:
        tables_after_upgrade = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert _NEW_TABLE in tables_after_upgrade

    command.downgrade(cfg, _PRIOR_REVISION)
    with engine.connect() as conn:
        tables_after_downgrade = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        index_names_after_downgrade = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
    assert _NEW_TABLE not in tables_after_downgrade
    assert not (_EXPECTED_INDEXES & index_names_after_downgrade)


def test_reupgrade_after_downgrade_recreates_the_table_cleanly(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        index_names = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
    assert _NEW_TABLE in tables
    assert _EXPECTED_INDEXES.issubset(index_names)
