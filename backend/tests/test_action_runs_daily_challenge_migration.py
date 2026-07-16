"""
Round-trip test for migrations/versions/0030_action_runs_daily_challenge.py
(Phase 2, Item 4 — Daily Breach action mode).

Same "stamp-then-step" approach as test_action_runs_migration.py: builds
the schema as of 0029 directly from the current ORM models (minus
action_runs itself, which 0029 introduces) and stamps Alembic to
"0029_action_runs" — upgrading to "0030_action_runs_daily_challenge" then
executes ONLY 0030's upgrade() in isolation.
"""
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.session import Base
import app.models  # noqa: F401 — ensure every model (incl. ActionRun) is registered

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TARGET_REVISION = "0030_action_runs_daily_challenge"


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg


@pytest.fixture
def migration_engine(tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'action_runs_daily_challenge_migration.db'}"
    engine = create_engine(sqlite_url)
    # Baseline = every current ORM table EXCEPT action_runs (0029 creates
    # it; 0030 only ALTERs it, so action_runs must not already exist when
    # 0029 itself runs during setup below).
    baseline_tables = [t for name, t in Base.metadata.tables.items() if name != "action_runs"]
    Base.metadata.create_all(engine, tables=baseline_tables)
    cfg = _alembic_config(sqlite_url)

    original_sync_url = settings.SYNC_DATABASE_URL
    settings.SYNC_DATABASE_URL = sqlite_url
    try:
        command.stamp(cfg, "0028_teaser_events")
        command.upgrade(cfg, "0029_action_runs")  # real 0029 upgrade, not a stamp — action_runs must actually exist
        command.stamp(cfg, "0029_action_runs")
        yield engine, cfg
    finally:
        settings.SYNC_DATABASE_URL = original_sync_url
        engine.dispose()


def _insert_daily_challenge(conn, challenge_id: str, scenario_id: str, challenge_date: str, challenge_number: int) -> None:
    conn.execute(
        text("""
            INSERT INTO daily_challenges (id, scenario_id, challenge_date, challenge_number, is_active, total_attempts, created_at)
            VALUES (:id, :scenario_id, :challenge_date, :challenge_number, 1, 0, CURRENT_TIMESTAMP)
        """),
        {"id": challenge_id, "scenario_id": scenario_id, "challenge_date": challenge_date, "challenge_number": challenge_number},
    )


def test_upgrade_adds_daily_challenge_id_column(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(action_runs)"))}
    assert "daily_challenge_id" in columns


def test_daily_challenge_id_is_nullable_for_non_daily_runs(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO action_runs
                (id, user_id, scenario_id, daily_challenge_id, seed, mode, action_log, score_breakdown, total_score, duration_seconds, outcome, created_at)
            VALUES
                ('run-scenario-1', NULL, 'scenario-1', NULL, 1, 'scenario', '[]', '{}', 0, 60, 'win', CURRENT_TIMESTAMP)
        """))
    with engine.connect() as conn:
        row = conn.execute(text("SELECT daily_challenge_id FROM action_runs WHERE id = 'run-scenario-1'")).fetchone()
    assert row.daily_challenge_id is None


def test_one_action_run_per_user_per_daily_challenge(migration_engine):
    """The whole point of the migration: a second row for the same
    (daily_challenge_id, user_id) pair must be rejected at the DB level,
    the same guarantee uq_daily_attempt_user already gives the
    decision-gate path."""
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.begin() as conn:
        _insert_daily_challenge(conn, "challenge-1", "scenario-1", "2026-07-16", 1)
        conn.execute(text("""
            INSERT INTO action_runs
                (id, user_id, scenario_id, daily_challenge_id, seed, mode, action_log, score_breakdown, total_score, duration_seconds, outcome, created_at)
            VALUES
                ('run-daily-1', 'user-1', 'scenario-1', 'challenge-1', 99, 'daily', '[]', '{}', 500, 200, 'win', CURRENT_TIMESTAMP)
        """))

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO action_runs
                    (id, user_id, scenario_id, daily_challenge_id, seed, mode, action_log, score_breakdown, total_score, duration_seconds, outcome, created_at)
                VALUES
                    ('run-daily-2', 'user-1', 'scenario-1', 'challenge-1', 99, 'daily', '[]', '{}', 10, 50, 'loss', CURRENT_TIMESTAMP)
            """))


def test_two_different_users_can_each_have_one_run_on_the_same_daily_challenge(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.begin() as conn:
        _insert_daily_challenge(conn, "challenge-1", "scenario-1", "2026-07-16", 1)
        for i, user_id in enumerate(("user-1", "user-2")):
            conn.execute(text("""
                INSERT INTO action_runs
                    (id, user_id, scenario_id, daily_challenge_id, seed, mode, action_log, score_breakdown, total_score, duration_seconds, outcome, created_at)
                VALUES
                    (:id, :user_id, 'scenario-1', 'challenge-1', 99, 'daily', '[]', '{}', :score, 200, 'win', CURRENT_TIMESTAMP)
            """), {"id": f"run-daily-{i}", "user_id": user_id, "score": 100 * (i + 1)})

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM action_runs WHERE daily_challenge_id = 'challenge-1'")).scalar()
    assert count == 2


def test_null_daily_challenge_id_rows_never_collide_with_each_other(migration_engine):
    """Multiple scenario/teaser-mode runs (daily_challenge_id IS NULL) for
    the SAME user must NOT be rejected — a UNIQUE constraint never treats
    two NULLs as duplicates, under either Postgres or SQLite."""
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.begin() as conn:
        for i in range(3):
            conn.execute(text("""
                INSERT INTO action_runs
                    (id, user_id, scenario_id, daily_challenge_id, seed, mode, action_log, score_breakdown, total_score, duration_seconds, outcome, created_at)
                VALUES
                    (:id, 'user-1', 'scenario-1', NULL, :seed, 'scenario', '[]', '{}', 0, 60, 'win', CURRENT_TIMESTAMP)
            """), {"id": f"run-{i}", "seed": i})

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM action_runs WHERE user_id = 'user-1'")).scalar()
    assert count == 3


def test_downgrade_removes_daily_challenge_id_cleanly(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)
    with engine.connect() as conn:
        columns_after_upgrade = {row[1] for row in conn.execute(text("PRAGMA table_info(action_runs)"))}
    assert "daily_challenge_id" in columns_after_upgrade

    command.downgrade(cfg, "0029_action_runs")
    with engine.connect() as conn:
        columns_after_downgrade = {row[1] for row in conn.execute(text("PRAGMA table_info(action_runs)"))}
    assert "daily_challenge_id" not in columns_after_downgrade

    # Re-upgrade must work too (no partial state left behind).
    command.upgrade(cfg, _TARGET_REVISION)
    with engine.connect() as conn:
        columns_after_reupgrade = {row[1] for row in conn.execute(text("PRAGMA table_info(action_runs)"))}
    assert "daily_challenge_id" in columns_after_reupgrade
