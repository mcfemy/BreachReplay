"""
Round-trip test for migrations/versions/0031_scenario_is_synthetic.py (the
daily-challenge picker's structural fix — see docs/BACKLOG.md's "Daily-
challenge picker can select synthetic/test-titled scenarios" entry).

Same "stamp-then-step" approach as test_action_runs_daily_challenge_migration.py,
adapted for an ALTER on an already-existing table rather than a brand-new
one: 0030/0029's tests exclude action_runs entirely from their baseline
`create_all` (that table doesn't exist yet at their starting revision), but
`scenarios` has existed since the very first migration — 0031 only adds one
column to it. `Base.metadata` is built from the CURRENT ORM model, which
already includes `Scenario.is_synthetic`, so `create_all` can't be used
as-is for the "before 0031" baseline; `_pre_0031_metadata` below copies
every table over via `to_metadata` except `scenarios`, whose columns are
copied individually with `is_synthetic` left out.
"""
import os
import warnings

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, text

from app.core.config import settings
from app.db.session import Base
import app.models  # noqa: F401 — ensure every model (incl. Scenario) is registered

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TARGET_REVISION = "0031_scenario_is_synthetic"
_PRIOR_REVISION = "0030_action_runs_daily_challenge"

# The exact titles migration 0031's upgrade() bulk-remediates — mirrored
# here (not imported) since a migration's own logic should be exercised
# byte-for-byte as authored, the same way the migration file itself doesn't
# import from application code.
_LEAKED_TEST_TITLES = (
    "WS Handler Test Scenario",
    "Daily Action Mode Test Scenario",
    "Org Tabletop Regression Scenario",
)


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg


def _pre_0031_metadata() -> MetaData:
    """Every current ORM table, except `scenarios` loses its
    `is_synthetic` column — reproducing the schema exactly as it existed
    at 0030, since `Base.metadata` (built from the current model) already
    has the column 0031 introduces."""
    baseline = MetaData()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # Column.copy() (SQLAlchemy 1.4+)
        for table in Base.metadata.sorted_tables:
            if table.name == "scenarios":
                cols = [c.copy() for c in table.columns if c.name != "is_synthetic"]
                Table(table.name, baseline, *cols)
            else:
                table.to_metadata(baseline)
    return baseline


@pytest.fixture
def migration_engine(tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'scenario_is_synthetic_migration.db'}"
    engine = create_engine(sqlite_url)
    _pre_0031_metadata().create_all(engine)
    cfg = _alembic_config(sqlite_url)

    original_sync_url = settings.SYNC_DATABASE_URL
    settings.SYNC_DATABASE_URL = sqlite_url
    try:
        command.stamp(cfg, _PRIOR_REVISION)
        yield engine, cfg
    finally:
        settings.SYNC_DATABASE_URL = original_sync_url
        engine.dispose()


def _insert_scenario(conn, scenario_id: str, title: str, status: str = "approved") -> None:
    # Every NOT NULL column whose default is Python-side only (set by the
    # ORM, not the DB) needs an explicit value here — this raw INSERT
    # bypasses the ORM entirely, the same reason test_action_runs_
    # migration.py's own insert helpers spell out every column rather than
    # relying on model defaults.
    conn.execute(
        text("""
            INSERT INTO scenarios
                (id, title, source_type, difficulty, estimated_minutes, compression_ratio,
                 status, is_private, version, play_count, created_at, updated_at)
            VALUES
                (:id, :title, 'manual', 'practitioner', 45, 8.0,
                 :status, 0, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """),
        {"id": scenario_id, "title": title, "status": status},
    )


def test_upgrade_adds_is_synthetic_column_defaulting_false(migration_engine):
    """The real gap the reviewer flagged: 0031's upgrade() must actually
    run (not just exist) against a schema that doesn't have the column
    yet, and existing rows must backfill to False via the server_default —
    not NULL, which every call site's `Scenario.is_synthetic.is_(False)`
    filter would silently mis-handle."""
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-real-1", "Colonial Pipeline Ransomware Attack")

    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(scenarios)"))}
        assert "is_synthetic" in columns

        value = conn.execute(
            text("SELECT is_synthetic FROM scenarios WHERE id = 'scenario-real-1'")
        ).scalar()
    assert value in (0, False)


def test_upgrade_archives_and_flags_known_leaked_test_titles(migration_engine):
    """The bulk remediation half of 0031: pre-existing rows matching the
    known leaked test-fixture titles must come out is_synthetic=True AND
    status='archived' — a real scenario's row must be untouched."""
    engine, cfg = migration_engine
    with engine.begin() as conn:
        for i, title in enumerate(_LEAKED_TEST_TITLES):
            _insert_scenario(conn, f"scenario-leaked-{i}", title, status="approved")
        _insert_scenario(conn, "scenario-real-1", "Colonial Pipeline Ransomware Attack")

    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        leaked_rows = conn.execute(
            text("SELECT is_synthetic, status FROM scenarios WHERE id LIKE 'scenario-leaked-%'")
        ).fetchall()
        real_row = conn.execute(
            text("SELECT is_synthetic, status FROM scenarios WHERE id = 'scenario-real-1'")
        ).fetchone()

    assert len(leaked_rows) == len(_LEAKED_TEST_TITLES)
    for is_synthetic, status in leaked_rows:
        assert is_synthetic in (1, True)
        assert status == "archived"

    assert real_row.is_synthetic in (0, False)
    assert real_row.status == "approved"


def test_downgrade_drops_is_synthetic_but_does_not_unarchive(migration_engine):
    """Downgrade cleanly removes the column. The status='archived' data
    mutation is a deliberate one-time remediation, not a reversible schema
    change — downgrade must NOT restore 'approved', and this asserts that
    explicitly rather than leaving it as untested, silent behavior."""
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-leaked-0", _LEAKED_TEST_TITLES[0], status="approved")

    command.upgrade(cfg, _TARGET_REVISION)
    with engine.connect() as conn:
        status_after_upgrade = conn.execute(
            text("SELECT status FROM scenarios WHERE id = 'scenario-leaked-0'")
        ).scalar()
    assert status_after_upgrade == "archived"

    command.downgrade(cfg, _PRIOR_REVISION)
    with engine.connect() as conn:
        columns_after_downgrade = {row[1] for row in conn.execute(text("PRAGMA table_info(scenarios)"))}
        status_after_downgrade = conn.execute(
            text("SELECT status FROM scenarios WHERE id = 'scenario-leaked-0'")
        ).scalar()
    assert "is_synthetic" not in columns_after_downgrade
    assert status_after_downgrade == "archived", (
        "downgrade must not un-archive — that data mutation is deliberate and one-way"
    )


def test_reupgrade_after_downgrade_restores_the_column_cleanly(migration_engine):
    engine, cfg = migration_engine
    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)

    command.upgrade(cfg, _TARGET_REVISION)
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(scenarios)"))}
    assert "is_synthetic" in columns
