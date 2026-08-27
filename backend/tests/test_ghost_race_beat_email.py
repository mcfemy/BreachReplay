"""Beat-notification email delivery for ghost_race_beats rows."""
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from app.core.security import hash_password
from app.db.session import SyncSessionLocal
from app.models.action_run import ActionRun
from app.models.ghost_race_beat import GhostRaceBeat
from app.models.organization import Organization
from app.models.scenario import Scenario
from app.models.user import User
from app.services.ghost_race_beat_email import (
    BEAT_EMAIL_DAILY_CAP,
    process_beat_notification_email,
)


@pytest.fixture
def sync_db():
    with SyncSessionLocal() as db:
        yield db
        db.rollback()


@pytest.fixture
def sync_org(sync_db):
    org = Organization(name="Email Test Org", slug=f"email-org-{uuid.uuid4().hex[:8]}")
    sync_db.add(org)
    sync_db.flush()
    return org


def _insert_scenario(db, scenario_id: str, title: str = "Cap Test Scenario") -> Scenario:
    scenario = Scenario(
        id=scenario_id,
        title=title,
        source_type="manual",
        source_reference=f"REF-{scenario_id[:8]}",
        difficulty="practitioner",
        status="approved",
        compression_ratio=1.0,
        alert_sequence=[],
    )
    db.add(scenario)
    db.flush()
    return scenario


def _insert_action_run(db, run_id: str, user_id: str, scenario_id: str) -> ActionRun:
    run = ActionRun(
        id=run_id,
        user_id=user_id,
        scenario_id=scenario_id,
        seed=42,
        mode="scenario",
        action_log=[],
        score_breakdown={},
        total_score=100,
        duration_seconds=120,
        outcome="contained",
        public_snapshot={"hosts": [], "edges": [], "techniques_encountered": []},
    )
    db.add(run)
    db.flush()
    return run


def _insert_beat(
    db,
    *,
    owner: User,
    racer: User,
    scenario: Scenario,
    notifications_enabled: bool = True,
    email_sent_at=None,
    email_delivered_at=None,
) -> GhostRaceBeat:
    ghost_run_id = str(uuid.uuid4())
    racer_run_id = str(uuid.uuid4())
    _insert_action_run(db, ghost_run_id, owner.id, scenario.id)
    _insert_action_run(db, racer_run_id, racer.id, scenario.id)
    beat = GhostRaceBeat(
        racer_user_id=racer.id,
        racer_action_run_id=racer_run_id,
        ghost_action_run_id=ghost_run_id,
        ghost_owner_user_id=owner.id,
        ghost_owner_beat_notifications_enabled=notifications_enabled,
        racer_containment_seconds=90,
        ghost_containment_seconds=150,
        beat_at=datetime.utcnow(),
        email_sent_at=email_sent_at,
        email_delivered_at=email_delivered_at,
    )
    db.add(beat)
    db.commit()
    db.refresh(beat)
    return beat


@patch("app.services.ghost_race_beat_email.send_ghost_race_beat_email", return_value=True)
def test_process_sends_and_marks_email_sent_at(mock_send, sync_db, sync_org):
    owner = User(
        email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Ghost Owner",
        role="analyst",
        organization_id=sync_org.id,
    )
    racer = User(
        email=f"racer-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Fast Racer",
        role="analyst",
        organization_id=sync_org.id,
    )
    sync_db.add_all([owner, racer])
    sync_db.flush()
    scenario = _insert_scenario(sync_db, str(uuid.uuid4()))
    beat = _insert_beat(sync_db, owner=owner, racer=racer, scenario=scenario)

    result = process_beat_notification_email(beat.id)
    assert result == "sent"
    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["racer_label"] == "Fast Racer"
    assert call_kwargs["scenario_title"] == scenario.title
    assert call_kwargs["seconds_faster"] == 60
    assert "unsubscribe?token=" in call_kwargs["unsubscribe_url"]

    with SyncSessionLocal() as verify_db:
        refreshed = verify_db.get(GhostRaceBeat, beat.id)
        assert refreshed.email_sent_at is not None
        assert refreshed.email_delivered_at is not None


@patch("app.services.ghost_race_beat_email.send_ghost_race_beat_email", return_value=True)
def test_process_opt_out_marks_row_without_sendgrid(mock_send, sync_db, sync_org):
    owner = User(
        email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Ghost Owner",
        role="analyst",
        organization_id=sync_org.id,
        beat_notifications_enabled=False,
    )
    racer = User(
        email=f"racer-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Racer",
        role="analyst",
        organization_id=sync_org.id,
    )
    sync_db.add_all([owner, racer])
    sync_db.flush()
    scenario = _insert_scenario(sync_db, str(uuid.uuid4()))
    beat = _insert_beat(
        sync_db, owner=owner, racer=racer, scenario=scenario, notifications_enabled=False,
    )

    result = process_beat_notification_email(beat.id)
    assert result == "skipped_opt_out"
    mock_send.assert_not_called()

    with SyncSessionLocal() as verify_db:
        refreshed = verify_db.get(GhostRaceBeat, beat.id)
        assert refreshed.email_sent_at is not None
        assert refreshed.email_delivered_at is None


@patch("app.services.ghost_race_beat_email.send_ghost_race_beat_email", return_value=True)
def test_process_is_idempotent_against_double_send(mock_send, sync_db, sync_org):
    owner = User(
        email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Ghost Owner",
        role="analyst",
        organization_id=sync_org.id,
    )
    racer = User(
        email=f"racer-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Racer",
        role="analyst",
        organization_id=sync_org.id,
    )
    sync_db.add_all([owner, racer])
    sync_db.flush()
    scenario = _insert_scenario(sync_db, str(uuid.uuid4()))
    beat = _insert_beat(sync_db, owner=owner, racer=racer, scenario=scenario)

    assert process_beat_notification_email(beat.id) == "sent"
    assert process_beat_notification_email(beat.id) == "already_processed"
    mock_send.assert_called_once()


@patch("app.services.ghost_race_beat_email.send_ghost_race_beat_email", return_value=True)
def test_process_daily_cap_blocks_send_after_limit(mock_send, sync_db, sync_org):
    owner = User(
        email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Popular Ghost Owner",
        role="analyst",
        organization_id=sync_org.id,
    )
    racer = User(
        email=f"racer-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Racer",
        role="analyst",
        organization_id=sync_org.id,
    )
    sync_db.add_all([owner, racer])
    sync_db.flush()
    scenario = _insert_scenario(sync_db, str(uuid.uuid4()))
    now = datetime.utcnow()

    for _ in range(BEAT_EMAIL_DAILY_CAP):
        _insert_beat(
            sync_db,
            owner=owner,
            racer=racer,
            scenario=scenario,
            email_sent_at=now,
            email_delivered_at=now,
        )

    capped_beat = _insert_beat(sync_db, owner=owner, racer=racer, scenario=scenario)
    result = process_beat_notification_email(capped_beat.id)
    assert result == "skipped_daily_cap"
    mock_send.assert_not_called()

    with SyncSessionLocal() as verify_db:
        refreshed = verify_db.get(GhostRaceBeat, capped_beat.id)
        assert refreshed.email_sent_at is not None
        assert refreshed.email_delivered_at is None

        delivered_count = verify_db.scalar(
            select(func.count())
            .select_from(GhostRaceBeat)
            .where(
                GhostRaceBeat.ghost_owner_user_id == owner.id,
                GhostRaceBeat.email_delivered_at.is_not(None),
                GhostRaceBeat.email_delivered_at >= now.replace(hour=0, minute=0, second=0, microsecond=0),
            )
        )
        assert delivered_count == BEAT_EMAIL_DAILY_CAP
