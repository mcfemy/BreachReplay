import pytest
from unittest.mock import MagicMock
from sqlalchemy import select

from app.models.session import SimulationSession, SessionParticipant, SessionDecision
from app.models.user import User
from app.core.security import hash_password
from app.websocket.manager import manager, build_alert_event, build_decision_gate_event, build_system_event
from app.websocket.handlers import _stream_alerts

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─── REST Multiplayer Join & Listing Tests ────────────────────────────────────

async def test_join_session_success(client, test_user, approved_scenario, db):
    """A standard analyst in the organization can claim a role and join team sessions."""
    # 1. Create a session
    create_resp = await client.post(
        "/api/v1/sessions",
        headers=auth_headers(test_user["token"]),
        json={"scenario_id": approved_scenario.id, "mode": "multiplayer"},
    )
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    # 2. Another user in same org joins as communications lead
    other_user = User(
        email="comms@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Communications Specialist",
        role="analyst",
        organization_id=test_user["org"].id,
    )
    db.add(other_user)
    await db.flush()

    from app.core.security import create_access_token
    other_token = create_access_token({"sub": other_user.id})

    join_resp = await client.post(
        f"/api/v1/sessions/{session_id}/join",
        headers=auth_headers(other_token),
        json={"role": "communications_lead"},
    )
    assert join_resp.status_code == 201
    data = join_resp.json()
    assert data["role"] == "communications_lead"
    assert data["user_id"] == other_user.id
    assert data["session_id"] == session_id

    # Verify database state
    result = await db.execute(
        select(SessionParticipant).where(
            SessionParticipant.session_id == session_id,
            SessionParticipant.user_id == other_user.id
        )
    )
    part = result.scalar_one_or_none()
    assert part is not None
    assert part.role == "communications_lead"


async def test_join_session_as_incident_commander_duplicate_fails(client, test_user, approved_scenario, db):
    """Prevent claiming the Incident Commander seat if it is already claimed by the host."""
    create_resp = await client.post(
        "/api/v1/sessions",
        headers=auth_headers(test_user["token"]),
        json={"scenario_id": approved_scenario.id, "mode": "multiplayer"},
    )
    session_id = create_resp.json()["id"]

    # Create another analyst trying to hijack the commander seat
    other_user = User(
        email="hijacker@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Hijacker Analyst",
        role="analyst",
        organization_id=test_user["org"].id,
    )
    db.add(other_user)
    await db.flush()

    from app.core.security import create_access_token
    other_token = create_access_token({"sub": other_user.id})

    join_resp = await client.post(
        f"/api/v1/sessions/{session_id}/join",
        headers=auth_headers(other_token),
        json={"role": "incident_commander"},
    )
    assert join_resp.status_code == 400
    assert "Incident Commander seat is already occupied" in join_resp.json()["detail"]


async def test_join_session_wrong_organization_fails(client, test_user, approved_scenario, db):
    """Enforce strict organization scoping to prevent cross-tenant simulation eavesdropping."""
    create_resp = await client.post(
        "/api/v1/sessions",
        headers=auth_headers(test_user["token"]),
        json={"scenario_id": approved_scenario.id, "mode": "multiplayer"},
    )
    session_id = create_resp.json()["id"]

    # Create user in another organization
    from app.models.organization import Organization
    other_org = Organization(name="Spy Corp", slug="spy-corp-slug")
    db.add(other_org)
    await db.flush()

    spy_user = User(
        email="spy@spycorp.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Spy Analyst",
        role="analyst",
        organization_id=other_org.id,
    )
    db.add(spy_user)
    await db.flush()

    from app.core.security import create_access_token
    spy_token = create_access_token({"sub": spy_user.id})

    join_resp = await client.post(
        f"/api/v1/sessions/{session_id}/join",
        headers=auth_headers(spy_token),
        json={"role": "soc_analyst"},
    )
    assert join_resp.status_code == 403


async def test_list_participants_success(client, test_user, approved_scenario, db):
    """Analysts can retrieve all active team seats in a simulation room."""
    create_resp = await client.post(
        "/api/v1/sessions",
        headers=auth_headers(test_user["token"]),
        json={"scenario_id": approved_scenario.id, "mode": "multiplayer"},
    )
    session_id = create_resp.json()["id"]

    list_resp = await client.get(
        f"/api/v1/sessions/{session_id}/participants",
        headers=auth_headers(test_user["token"]),
    )
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert isinstance(data, list)
    assert len(data) == 1  # Host was automatically added in creation
    assert data[0]["user_id"] == test_user["user"].id
    assert data[0]["role"] == "incident_commander"


# ─── WebSocket State Machine Unit Tests ───────────────────────────────────────

async def test_manager_presence_tracking():
    """Verify ConnectionManager correctly updates active analyst presence directories."""
    session_id = "test-session-uuid"
    user_id = "user-analyst-uuid"
    mock_ws = MagicMock()

    manager.presence = {}  # Reset state

    # Add presence
    await manager.add_user_presence(session_id, user_id, "Jane Analyst", "forensic_analyst", mock_ws)
    assert session_id in manager.presence
    assert user_id in manager.presence[session_id]
    assert manager.presence[session_id][user_id]["name"] == "Jane Analyst"
    assert manager.presence[session_id][user_id]["role"] == "forensic_analyst"
    assert manager.presence[session_id][user_id]["online"] is True

    # Mark offline
    await manager.remove_user_presence(session_id, user_id)
    assert manager.presence[session_id][user_id]["online"] is False


async def test_manager_voting_consensus():
    """Verify ConnectionManager correctly tallies collaborative decision votes and resets."""
    session_id = "vote-session-uuid"
    u1 = "user-1"
    u2 = "user-2"

    manager.votes = {}  # Reset state

    # Record votes
    manager.record_vote(session_id, u1, 1)
    manager.record_vote(session_id, u2, 2)
    assert manager.votes[session_id][u1] == 1
    assert manager.votes[session_id][u2] == 2

    # Clear votes
    manager.clear_votes(session_id)
    assert manager.votes[session_id] == {}


async def test_manager_play_pause_controls():
    """Verify ConnectionManager manages play/pause non-blocking event loops cleanly."""
    session_id = "play-pause-session-uuid"
    manager.pause_events = {}  # Reset state
    manager.statuses = {}

    # Check default running
    event = manager.get_pause_event(session_id)
    assert event.is_set() is True
    assert manager.is_paused(session_id) is False

    # Pause session
    manager.pause_session(session_id)
    assert event.is_set() is False
    assert manager.is_paused(session_id) is True
    assert manager.statuses[session_id] == "paused"

    # Resume session
    manager.resume_session(session_id)
    assert event.is_set() is True
    assert manager.is_paused(session_id) is False
    assert manager.statuses[session_id] == "active"


async def test_manager_alert_injections():
    """Verify ConnectionManager successfully queues facilitator alerts."""
    session_id = "inject-session-uuid"
    manager.inject_queues = {}  # Reset state

    dummy_alert = {"timestamp": "+5m", "description": "Facilitator Malware Injection"}
    manager.queue_inject_alert(session_id, dummy_alert)

    # Pop alerts
    injected = manager.pop_injected_alerts(session_id)
    assert len(injected) == 1
    assert injected[0]["description"] == "Facilitator Malware Injection"

    # Queue should be empty now
    assert manager.pop_injected_alerts(session_id) == []
