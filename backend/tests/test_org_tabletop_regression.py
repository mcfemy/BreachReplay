"""
Regression test for Phase 2 (BREACHREPLAY_GAME_OVERHAUL_SPEC.md section 4 /
docs/PHASE2_KICKOFF.md Part B, Item 3): proves the OLD decision-gate
WebSocket message types (org tabletop mode) are completely unaffected by
the new action-console WS wiring (action_run_ws_handler,
app.services.action_run_store, the new manager.py builders). Exercises
simulation_ws_handler directly end to end — chat, ping, submit_vote, and
submit_command_decision — the same handler function and message-type
branches that existed before Item 3, untouched by it.

WS-handler testing convention (see test_arena_spectator.py's module
docstring): a minimal FakeWebSocket double, called directly rather than
through a real ASGI transport. Uses AsyncSessionLocal directly (not the
`db`/`test_user` fixtures) since simulation_ws_handler opens its own
AsyncSessionLocal() sessions internally — a different connection than the
`db` fixture's rolled-back transaction.
"""
import uuid

import pytest
from fastapi import WebSocketDisconnect
from sqlalchemy import select

from app.models.scenario import Scenario
from app.models.session import SessionDecision, SessionParticipant, SimulationSession
from app.websocket.handlers import simulation_ws_handler
from app.websocket.manager import manager

pytestmark = pytest.mark.asyncio

_DECISION_TREE = [
    {
        "id": "gate-001",
        "trigger_timestamp": "+15m",
        "context_summary": "Suspicious lateral movement detected.",
        "options": [
            {"text": "Isolate host", "consequence_if_chosen": "Containment initiated"},
            {"text": "Ignore alert", "consequence_if_chosen": "Attacker spreads"},
        ],
        "correct_index": 0,
        "consequence_if_wrong": "Attacker maintains persistence.",
        "consequence_if_correct": "Good call.",
        "rationale": "NIST RS.CO-1 requires immediate containment.",
        "nist_control_ref": "RS.CO-1",
        "mitre_technique": "T1021",
    }
]


class FakeWebSocket:
    """Same minimal double used by test_arena_spectator.py /
    test_action_run_ws_handler.py — simulation_ws_handler only ever calls
    .send_json/.receive_text on it."""

    def __init__(self, incoming: list | None = None):
        self.sent: list[dict] = []
        self._incoming = list(incoming or [])

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def receive_text(self) -> str:
        if self._incoming:
            return self._incoming.pop(0)
        raise WebSocketDisconnect(code=1000)


async def _make_org_tabletop_session(user_id: str):
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        scenario = Scenario(
            id=str(uuid.uuid4()),
            title="Org Tabletop Regression Scenario",
            source_type="manual",
            source_reference=f"TEST-ORG-{uuid.uuid4().hex[:8]}",
            difficulty="practitioner",
            status="approved",
            decision_tree=_DECISION_TREE,
            alert_sequence=[],
        )
        db.add(scenario)
        await db.flush()

        session = SimulationSession(
            id=str(uuid.uuid4()),
            scenario_id=scenario.id,
            host_user_id=user_id,
            status="active",
            mode="multiplayer",
        )
        db.add(session)
        await db.flush()

        participant = SessionParticipant(
            id=str(uuid.uuid4()),
            session_id=session.id,
            user_id=user_id,
            role="incident_commander",
        )
        db.add(participant)
        await db.commit()
        await db.refresh(session)
        return scenario, session


async def test_org_tabletop_decision_gate_flow_is_unaffected_by_phase_2():
    from tests.conftest import ensure_test_user_row
    from app.db.session import AsyncSessionLocal

    user_id = "org-tabletop-user-1"
    await ensure_test_user_row(user_id)
    scenario, session = await _make_org_tabletop_session(user_id)

    ws = FakeWebSocket(incoming=[
        '{"type": "ping"}',
        '{"type": "chat", "text": "Team, let\'s isolate that host."}',
        '{"type": "submit_vote", "chosen_option_index": 0}',
        '{"type": "submit_command_decision", "decision_gate_id": "gate-001", "chosen_option_index": 0, "response_time_seconds": 12}',
    ])

    try:
        await simulation_ws_handler(ws, session.id, user_id)
    finally:
        # simulation_ws_handler's own disconnect path only runs on
        # WebSocketDisconnect from inside its loop, which it is here (the
        # FakeWebSocket raises once the queue empties) — but explicitly
        # clean up manager state too, mirroring test_multiplayer.py's
        # convention of not leaking presence/connection state across tests.
        manager.disconnect(session.id, ws)

    types = [m["type"] for m in ws.sent]
    assert "pong" in types
    assert "chat" in types
    assert "vote_update" in types
    assert "decision_result" in types

    decision_result = next(m for m in ws.sent if m["type"] == "decision_result")
    assert decision_result["decision_gate_id"] == "gate-001"
    assert decision_result["is_correct"] is True
    assert decision_result["correct_index"] == 0

    chat_event = next(m for m in ws.sent if m["type"] == "chat")
    assert chat_event["text"] == "Team, let's isolate that host."
    assert chat_event["role"] == "incident_commander"

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SessionDecision).where(SessionDecision.session_id == session.id)
        )
        decision = result.scalar_one()
        assert decision.decision_gate_id == "gate-001"
        assert decision.chosen_option_index == 0
        assert decision.is_correct is True
        assert decision.response_time_seconds == 12
        assert decision.nist_control_ref == "RS.CO-1"
        assert decision.mitre_technique == "T1021"

        s_result = await db.execute(select(SimulationSession).where(SimulationSession.id == session.id))
        refreshed_session = s_result.scalar_one()
        assert refreshed_session.decisions_made == 1
        assert refreshed_session.decisions_correct == 1
