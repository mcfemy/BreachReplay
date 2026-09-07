"""
Round-trip test for migrations/versions/0050_action_run_length_mode.py.
"""
import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.db.session import Base
import app.models  # noqa: F401

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TARGET_REVISION = "0050_action_run_length_mode"
_PRIOR_REVISION = "0049_colonial_notification_matrix"

_NEW_COLUMNS = {"length_mode", "cap_seconds", "compression_ratio"}


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg


def _pre_0050_metadata() -> sa.MetaData:
    """Current ORM schema minus the three columns 0050 adds to action_runs."""
    baseline = sa.MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name != "action_runs":
            table.to_metadata(baseline)
            continue
        cols = [c.copy() for c in table.columns if c.name not in _NEW_COLUMNS]
        sa.Table(table.name, baseline, *cols, schema=table.schema)
    return baseline


@pytest.fixture
def migration_engine(tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'action_run_length_mode_migration.db'}"
    engine = create_engine(sqlite_url)
    _pre_0050_metadata().create_all(engine)
    cfg = _alembic_config(sqlite_url)

    original_sync_url = settings.SYNC_DATABASE_URL
    settings.SYNC_DATABASE_URL = sqlite_url
    try:
        command.stamp(cfg, _PRIOR_REVISION)
        yield engine, cfg
    finally:
        settings.SYNC_DATABASE_URL = original_sync_url
        engine.dispose()


def _insert_legacy_action_run(conn, run_id: str) -> None:
    """Insert a pre-0050-shaped row (no length columns) after creating FKs."""
    conn.execute(
        text("""
            INSERT INTO users (
                id, email, hashed_password, full_name, role, is_active,
                beat_notifications_enabled, email_unsubscribe_token,
                has_acknowledged_racing_notice, response_index,
                created_at, updated_at
            )
            VALUES (
                'u-legacy', 'legacy@example.com', 'x', 'Legacy', 'analyst', 1,
                1, 'tok-legacy', 0, 1200, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """)
    )
    conn.execute(
        text("""
            INSERT INTO scenarios (
                id, title, source_type, source_reference, difficulty,
                estimated_minutes, compression_ratio, status, is_synthetic,
                is_private, version, play_count, created_at, updated_at
            )
            VALUES (
                'scn-legacy', 'Legacy Scenario', 'manual', 'MIG-LEN-001', 'practitioner',
                45, 8.0, 'approved', 0, 0, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """)
    )
    conn.execute(
        text("""
            INSERT INTO action_runs (
                id, user_id, scenario_id, seed, mode, action_log,
                score_breakdown, total_score, duration_seconds, outcome,
                created_at
            )
            VALUES (
                :id, 'u-legacy', 'scn-legacy', 1, 'scenario', '[]',
                '{}', 0, 100, 'breached',
                CURRENT_TIMESTAMP
            )
        """),
        {"id": run_id},
    )


def test_upgrade_adds_length_columns_with_compressed_default(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_legacy_action_run(conn, "run-legacy")

    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(action_runs)"))}
        assert _NEW_COLUMNS.issubset(columns)
        row = conn.execute(
            text(
                "SELECT length_mode, cap_seconds, compression_ratio "
                "FROM action_runs WHERE id = 'run-legacy'"
            )
        ).one()
        assert row.length_mode == "compressed"
        assert row.cap_seconds is None
        assert row.compression_ratio is None


def test_downgrade_drops_length_columns(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(action_runs)"))}
        assert _NEW_COLUMNS.isdisjoint(columns)


def test_reupgrade_after_downgrade_restores_length_columns(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_legacy_action_run(conn, "run-re")

    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(action_runs)"))}
        assert _NEW_COLUMNS.issubset(columns)
        value = conn.execute(
            text("SELECT length_mode FROM action_runs WHERE id = 'run-re'")
        ).scalar_one()
        assert value == "compressed"
