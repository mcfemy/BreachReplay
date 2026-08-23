"""
Round-trip test for migrations/versions/0042_log4shell_notification_matrix.py
(Phase 3 — Targeted Escalation & Notification Proportionality, item 2 of 5).

Simpler than 0038's own round-trip test: 0042 doesn't add a column (that
happened in 0038, already on the ORM schema this test creates) — it's a
pure content backfill. Stamps at 0041 (current head before this revision)
then steps to 0042, same "stamp-then-step" approach as
test_scenario_notification_matrix_migration.py, minus the column-diffing
`_pre_*_metadata` step.
"""
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.db.session import Base
import app.models  # noqa: F401 — ensure every model (incl. Scenario) is registered

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TARGET_REVISION = "0042_log4shell_notification_matrix"
_PRIOR_REVISION = "0041_action_run_public_share"

_LOG4SHELL_SOURCE_REF = "CVE-2021-44228"


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg


@pytest.fixture
def migration_engine(tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'log4shell_notification_matrix_migration.db'}"
    engine = create_engine(sqlite_url)
    # Base.metadata already has notification_matrix (0038 landed it on the
    # current ORM model) — this test only exercises 0042's own backfill,
    # so the full current schema is the correct starting point once
    # stamped at 0041.
    Base.metadata.create_all(engine)
    cfg = _alembic_config(sqlite_url)

    original_sync_url = settings.SYNC_DATABASE_URL
    settings.SYNC_DATABASE_URL = sqlite_url
    try:
        command.stamp(cfg, _PRIOR_REVISION)
        yield engine, cfg
    finally:
        settings.SYNC_DATABASE_URL = original_sync_url
        engine.dispose()


def _insert_scenario(conn, scenario_id: str, source_reference: str) -> None:
    conn.execute(
        text("""
            INSERT INTO scenarios
                (id, title, source_type, source_reference, difficulty, estimated_minutes,
                 compression_ratio, status, is_synthetic, is_private, version, play_count,
                 created_at, updated_at, notification_matrix)
            VALUES
                (:id, 'Test Scenario', 'manual', :ref, 'practitioner', 45, 8.0,
                 'approved', 0, 0, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '[]')
        """),
        {"id": scenario_id, "ref": source_reference},
    )


def test_upgrade_backfills_log4shell_matrix_and_leaves_other_scenarios_empty(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-log4shell", _LOG4SHELL_SOURCE_REF)
        _insert_scenario(conn, "scenario-unrelated-1", "SOME-OTHER-SOURCE-REF")

    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        log4shell_value = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-log4shell'")
        ).scalar()
        other_value = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-unrelated-1'")
        ).scalar()

    import json
    log4shell_matrix = json.loads(log4shell_value) if isinstance(log4shell_value, str) else log4shell_value
    assert len(log4shell_matrix) == 6
    party_ids = {p["id"] for p in log4shell_matrix}
    assert party_ids == {"customer_contractual", "soc2_customers", "legal", "pr_comms", "cisa", "dhs_nation_state"}
    warranted_by_id = {p["id"]: p["warranted"] for p in log4shell_matrix}
    assert warranted_by_id["dhs_nation_state"] is False
    assert warranted_by_id["soc2_customers"] is True

    other_matrix = json.loads(other_value) if isinstance(other_value, str) else other_value
    assert other_matrix == []


def test_downgrade_clears_log4shell_matrix_back_to_empty(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-log4shell", _LOG4SHELL_SOURCE_REF)

    command.upgrade(cfg, _TARGET_REVISION)
    with engine.connect() as conn:
        value_after_upgrade = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-log4shell'")
        ).scalar()
    import json
    assert len(json.loads(value_after_upgrade) if isinstance(value_after_upgrade, str) else value_after_upgrade) == 6

    command.downgrade(cfg, _PRIOR_REVISION)
    with engine.connect() as conn:
        value_after_downgrade = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-log4shell'")
        ).scalar()
    matrix_after_downgrade = json.loads(value_after_downgrade) if isinstance(value_after_downgrade, str) else value_after_downgrade
    assert matrix_after_downgrade == []


def test_reupgrade_after_downgrade_restores_the_backfill_cleanly(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-log4shell", _LOG4SHELL_SOURCE_REF)

    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-log4shell'")
        ).scalar()
    import json
    matrix = json.loads(value) if isinstance(value, str) else value
    assert len(matrix) == 6
