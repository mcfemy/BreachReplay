"""
Round-trip test for migrations/versions/0029_action_runs.py (Phase 2,
Item 2).

Rather than replaying the entire migration history (0001..0028 — heavy on
Postgres-native JSONB/ARRAY/ENUM DDL) against SQLite, this builds the
schema as of 0028 directly from the current ORM models (Base.metadata,
already proven SQLite-safe by every other test in this suite) and stamps
Alembic to "0028_teaser_events" without running anything. `alembic upgrade
head` then executes ONLY 0029's `upgrade()` in isolation, which is what
this test actually needs to verify — not the rest of the history.
"""
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.db.session import Base
import app.models  # noqa: F401 — ensure every model (incl. ActionRun) is registered

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_EXPECTED_COLUMNS = {
    "id", "user_id", "scenario_id", "seed", "mode", "action_log",
    "score_breakdown", "total_score", "duration_seconds", "outcome", "created_at",
}


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg


@pytest.fixture
def migration_engine(tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'action_runs_migration.db'}"
    engine = create_engine(sqlite_url)
    # Build the "as of 0028" baseline schema — every current ORM table
    # EXCEPT action_runs itself (its ORM model, app.models.action_run.
    # ActionRun, is what 0029 introduces; leaving it in would make
    # create_all() create the very table 0029's upgrade() is about to
    # CREATE TABLE, colliding with it).
    baseline_tables = [t for name, t in Base.metadata.tables.items() if name != "action_runs"]
    Base.metadata.create_all(engine, tables=baseline_tables)
    cfg = _alembic_config(sqlite_url)

    # migrations/env.py ALWAYS reads settings.SYNC_DATABASE_URL (line 10:
    # `config.set_main_option("sqlalchemy.url", settings.SYNC_DATABASE_URL)`)
    # and overwrites whatever URL was passed via the Config object above —
    # so without this, every alembic command below would silently run
    # against the shared conftest.py test.db instead of this test's own
    # isolated tmp_path database. settings is a live, already-constructed
    # object (pydantic-settings reads env vars once at import time), so the
    # only way to redirect it is to patch the attribute directly.
    original_sync_url = settings.SYNC_DATABASE_URL
    settings.SYNC_DATABASE_URL = sqlite_url
    try:
        command.stamp(cfg, "0028_teaser_events")
        yield engine, cfg
    finally:
        settings.SYNC_DATABASE_URL = original_sync_url
        engine.dispose()


def test_upgrade_creates_action_runs_with_the_spec_columns(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(action_runs)"))}
    assert columns == _EXPECTED_COLUMNS


def test_upgrade_then_insert_select_round_trip(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, "head")

    # Bound parameters throughout — a literal '{"total":420}' inlined into
    # text() would otherwise get misparsed as a `:420` bind placeholder.
    insert_sql = text("""
        INSERT INTO action_runs
            (id, user_id, scenario_id, seed, mode, action_log, score_breakdown, duration_seconds, outcome, created_at)
        VALUES
            (:id, :user_id, :scenario_id, :seed, :mode, :action_log, :score_breakdown, :duration_seconds, :outcome, CURRENT_TIMESTAMP)
    """)
    insert_with_score_sql = text("""
        INSERT INTO action_runs
            (id, user_id, scenario_id, seed, mode, action_log, score_breakdown, total_score, duration_seconds, outcome, created_at)
        VALUES
            (:id, :user_id, :scenario_id, :seed, :mode, :action_log, :score_breakdown, :total_score, :duration_seconds, :outcome, CURRENT_TIMESTAMP)
    """)
    with engine.begin() as conn:
        # No total_score given — must fall back to the column's server_default.
        conn.execute(insert_sql, {
            "id": "run-teaser-1", "user_id": None, "scenario_id": "scenario-1", "seed": 42,
            "mode": "teaser", "action_log": "[]", "score_breakdown": "{}",
            "duration_seconds": 90, "outcome": "win",
        })
        conn.execute(insert_with_score_sql, {
            "id": "run-daily-1", "user_id": "user-1", "scenario_id": "scenario-1", "seed": 7,
            "mode": "daily", "action_log": '[{"verb":"scan_network"}]', "score_breakdown": '{"total":420}',
            "total_score": 420, "duration_seconds": 300, "outcome": "partial",
        })

    with engine.connect() as conn:
        teaser_row = conn.execute(
            text("SELECT user_id, mode, outcome, duration_seconds, total_score FROM action_runs WHERE id = 'run-teaser-1'")
        ).fetchone()
        daily_row = conn.execute(
            text("SELECT user_id, mode, outcome, action_log, total_score FROM action_runs WHERE id = 'run-daily-1'")
        ).fetchone()

    assert teaser_row.user_id is None  # nullable for teaser mode, per spec
    assert teaser_row.mode == "teaser"
    assert teaser_row.outcome == "win"
    assert teaser_row.duration_seconds == 90
    assert teaser_row.total_score == 0  # server_default="0"

    assert daily_row.user_id == "user-1"
    assert daily_row.mode == "daily"
    assert daily_row.outcome == "partial"
    assert "scan_network" in daily_row.action_log
    assert daily_row.total_score == 420

    # The whole point of a plain integer column: ORDER BY works like any
    # other leaderboard query, unlike sorting on a JSONB path.
    with engine.connect() as conn:
        ranked_ids = [
            row[0] for row in conn.execute(
                text("SELECT id FROM action_runs ORDER BY total_score DESC")
            )
        ]
    assert ranked_ids == ["run-daily-1", "run-teaser-1"]


def test_downgrade_drops_action_runs_cleanly(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        tables_after_upgrade = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert "action_runs" in tables_after_upgrade

    command.downgrade(cfg, "-1")
    with engine.connect() as conn:
        tables_after_downgrade = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert "action_runs" not in tables_after_downgrade

    # Re-upgrading after a downgrade must work too (proves downgrade left no
    # partial state behind, e.g. a stray enum type it failed to drop).
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        tables_after_reupgrade = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert "action_runs" in tables_after_reupgrade
