"""
Round-trip test for migrations/versions/0047_mgm_notification_matrix.py
(Phase 3 — Targeted Escalation & Notification Proportionality, item 3 of 5).

Same shape as test_log4shell_notification_matrix_migration.py: 0047 is a
pure content backfill (column already exists from 0038). Stamps at 0046
then steps to 0047.
"""
import json
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.db.session import Base
import app.models  # noqa: F401 — ensure every model (incl. Scenario) is registered
from seed import MGM_GRAND

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TARGET_REVISION = "0047_mgm_notification_matrix"
_PRIOR_REVISION = "0046_response_index"

_MGM_SOURCE_REF = "MGM-2023-SEC-8K"

_EXPECTED_PARTY_IDS = {
    "pci_card_brands",
    "fbi",
    "affected_guests",
    "sec",
    "legal",
    "caesars_quiet_payment",
}


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    return cfg


@pytest.fixture
def migration_engine(tmp_path):
    sqlite_url = f"sqlite:///{tmp_path / 'mgm_notification_matrix_migration.db'}"
    engine = create_engine(sqlite_url)
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


def _as_list(value):
    return json.loads(value) if isinstance(value, str) else value


def test_upgrade_backfills_mgm_matrix_and_leaves_other_scenarios_empty(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-mgm", _MGM_SOURCE_REF)
        _insert_scenario(conn, "scenario-unrelated-1", "SOME-OTHER-SOURCE-REF")

    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        mgm_value = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-mgm'")
        ).scalar()
        other_value = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-unrelated-1'")
        ).scalar()

    mgm_matrix = _as_list(mgm_value)
    assert len(mgm_matrix) == 6
    party_ids = {p["id"] for p in mgm_matrix}
    assert party_ids == _EXPECTED_PARTY_IDS
    warranted_by_id = {p["id"]: p["warranted"] for p in mgm_matrix}
    assert warranted_by_id["caesars_quiet_payment"] is False
    assert warranted_by_id["pci_card_brands"] is True
    assert warranted_by_id["fbi"] is True
    assert warranted_by_id["affected_guests"] is True
    assert warranted_by_id["sec"] is True
    assert warranted_by_id["legal"] is True

    other_matrix = _as_list(other_value)
    assert other_matrix == []


def test_migration_matrix_matches_seed_exactly(migration_engine):
    """Migration backfill and seed.MGM_GRAND must stay identical by hand —
    same discipline as SolarWinds 0038 / Log4Shell 0042."""
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-mgm", _MGM_SOURCE_REF)

    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-mgm'")
        ).scalar()

    assert _as_list(value) == MGM_GRAND["notification_matrix"]


def test_downgrade_clears_mgm_matrix_back_to_empty(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-mgm", _MGM_SOURCE_REF)

    command.upgrade(cfg, _TARGET_REVISION)
    with engine.connect() as conn:
        value_after_upgrade = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-mgm'")
        ).scalar()
    assert len(_as_list(value_after_upgrade)) == 6

    command.downgrade(cfg, _PRIOR_REVISION)
    with engine.connect() as conn:
        value_after_downgrade = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-mgm'")
        ).scalar()
    assert _as_list(value_after_downgrade) == []


def test_reupgrade_after_downgrade_restores_the_backfill_cleanly(migration_engine):
    engine, cfg = migration_engine
    with engine.begin() as conn:
        _insert_scenario(conn, "scenario-mgm", _MGM_SOURCE_REF)

    command.upgrade(cfg, _TARGET_REVISION)
    command.downgrade(cfg, _PRIOR_REVISION)
    command.upgrade(cfg, _TARGET_REVISION)

    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT notification_matrix FROM scenarios WHERE id = 'scenario-mgm'")
        ).scalar()
    matrix = _as_list(value)
    assert len(matrix) == 6
    assert {p["id"] for p in matrix} == _EXPECTED_PARTY_IDS
