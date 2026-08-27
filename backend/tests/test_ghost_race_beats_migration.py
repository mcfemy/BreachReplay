"""
Round-trip test for migrations/versions/0044_ghost_race_beats.py.
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
import app.models  # noqa: F401

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TARGET_REVISION = "0044_ghost_race_beats"
_PRIOR_REVISION = "0043_beat_notification_consent"

_NEW_TABLE = "ghost_race_beats"
_EXPECTED_INDEXES = {
    "ix_ghost_race_beats_racer_user_id",
    "ix_ghost_race_beats_ghost_action_run_id",
    "ix_ghost_race_beats_ghost_owner_user_id",
    "ix_ghost_race_beats_beat_at",
}
_EXPECTED_COLUMNS = {
    "id",
    "racer_user_id",
    "racer_action_run_id",
    "ghost_action_run_id",
    "ghost_owner_user_id",
    "ghost_owner_beat_notifications_enabled",
    "racer_containment_seconds",
    "ghost_containment_seconds",
    "beat_at",
}


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg


def _pre_0044_metadata() -> sa.MetaData:
    """Current ORM schema minus `ghost_race_beats` — the 0043 baseline."""
    baseline = sa.MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name == _NEW_TABLE:
            continue
        table.to_metadata(baseline)
    return baseline


@pytest.fixture
def migration_engine(tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'ghost_race_beats_migration.db'}"
    engine = create_engine(sqlite_url)
    _pre_0044_metadata().create_all(engine)
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
            INSERT INTO users (
                id, email, hashed_password, full_name, role, is_active,
                beat_notifications_enabled, email_unsubscribe_token,
                has_acknowledged_racing_notice, created_at, updated_at
            )
            VALUES (
                :id, :email, 'x', 'Test User', 'analyst', 1,
                1, :token, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """),
        {"id": user_id, "email": f"{user_id}@example.com", "token": f"tok-{user_id}"},
    )


def _insert_action_run(conn, run_id: str, user_id: str, scenario_id: str) -> None:
    conn.execute(
        text("""
            INSERT INTO action_runs (
                id, user_id, scenario_id, seed, mode, action_log,
                score_breakdown, total_score, duration_seconds, outcome,
                created_at
            )
            VALUES (
                :id, :user_id, :scenario_id, 1, 'scenario', '[]',
                '{}', 100, 120, 'contained', CURRENT_TIMESTAMP
            )
        """),
        {"id": run_id, "user_id": user_id, "scenario_id": scenario_id},
    )


def _insert_scenario(conn, scenario_id: str) -> None:
    conn.execute(
        text("""
            INSERT INTO scenarios (
                id, title, source_type, source_reference, difficulty,
                estimated_minutes, compression_ratio, status, is_synthetic,
                is_private, version, play_count, created_at, updated_at
            )
            VALUES (
                :id, 'Migration Test', 'manual', 'MIG-001', 'practitioner',
                45, 8.0, 'approved', 0, 0, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """),
        {"id": scenario_id},
    )


def test_upgrade_creates_ghost_race_beats_table_with_indexes_and_unique_constraint(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert _NEW_TABLE in tables

        columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({_NEW_TABLE})"))}
        assert columns == _EXPECTED_COLUMNS

        index_names = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
        assert _EXPECTED_INDEXES.issubset(index_names)
        assert "ix_ghost_race_beats_racer_action_run_id" not in index_names

        table_sql = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"),
            {"name": _NEW_TABLE},
        ).scalar()
        assert "uq_ghost_race_beats_racer_action_run" in table_sql


def test_upgrade_unique_constraint_rejects_duplicate_racer_action_run_id(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-1")
        _insert_user(conn, "owner-1")
        _insert_user(conn, "racer-1")
        _insert_action_run(conn, "ghost-run", "owner-1", "scenario-1")
        _insert_action_run(conn, "racer-run", "racer-1", "scenario-1")
        conn.execute(
            text("""
                INSERT INTO ghost_race_beats (
                    id, racer_user_id, racer_action_run_id, ghost_action_run_id,
                    ghost_owner_user_id, ghost_owner_beat_notifications_enabled,
                    racer_containment_seconds, ghost_containment_seconds, beat_at
                )
                VALUES (
                    'beat-1', 'racer-1', 'racer-run', 'ghost-run',
                    'owner-1', 1, 90, 120, CURRENT_TIMESTAMP
                )
            """)
        )
        with pytest.raises(IntegrityError):
            conn.execute(
                text("""
                    INSERT INTO ghost_race_beats (
                        id, racer_user_id, racer_action_run_id, ghost_action_run_id,
                        ghost_owner_user_id, ghost_owner_beat_notifications_enabled,
                        racer_containment_seconds, ghost_containment_seconds, beat_at
                    )
                    VALUES (
                        'beat-2', 'racer-1', 'racer-run', 'ghost-run',
                        'owner-1', 1, 80, 120, CURRENT_TIMESTAMP
                    )
                """)
            )


def test_downgrade_drops_ghost_race_beats_table(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)

    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert _NEW_TABLE not in tables


def test_reupgrade_after_downgrade_restores_table_and_indexes(migration_engine):
    """upgrade → downgrade → upgrade — the path criterion (g) requires CI to exercise."""
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert _NEW_TABLE in tables

        columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({_NEW_TABLE})"))}
        assert columns == _EXPECTED_COLUMNS

        index_names = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
        assert _EXPECTED_INDEXES.issubset(index_names)
