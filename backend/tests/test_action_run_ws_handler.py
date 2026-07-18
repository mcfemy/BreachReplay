"""
Tests for app.websocket.handlers.action_run_ws_handler (Phase 2, Item 3).

WS-handler testing convention (see test_arena_spectator.py's module
docstring for the full documented reasoning): starlette's
TestClient.websocket_connect is incompatible with this suite's
fakeredis-per-event-loop fixture, so action_run_ws_handler — which takes a
plain `websocket` argument and only ever calls .send_json/.receive_text/
.close on it — is tested by calling it directly with a minimal FakeWebSocket
double, the same approach used for arena_spectator_ws_handler.

Uses `app.db.session.AsyncSessionLocal` directly (not the `db`/`test_user`
fixtures) for anything the handler itself will read/write: it opens its own
AsyncSessionLocal() session internally (inside action_run_store.finalize),
a different connection than the `db` fixture's single rolled-back
transaction — writes made only through `db` would be invisible to it. This
mirrors test_arena_ai_attacker.py's/test_arena_spectator.py's documented
pattern exactly, including reusing conftest.ensure_test_user_row for the
user row.
"""
import uuid

import pytest
from fastapi import WebSocketDisconnect

from app.services import action_engine
from app.services.action_run_store import action_run_store
from app.websocket.handlers import action_run_ws_handler

pytestmark = pytest.mark.asyncio

# Short final-stage trigger (+2m = 120s) so tests that need a run to
# naturally conclude (is_run_over -> True) don't have to burn an
# unreasonable number of fake messages to get there.
_FAST_DECISION_TREE = [
    {"id": "gate-001", "trigger_timestamp": "+2m", "mitre_technique": "T1078",
     "context_summary": "Suspicious VPN activity.", "options": [], "correct_index": 0,
     "consequence_if_wrong": "Missed.", "rationale": "Correlate anomalies.", "nist_control_ref": "DE.AE-2"},
]


class FakeWebSocket:
    """Minimal double for starlette's WebSocket — identical shape to
    test_arena_spectator.py's FakeWebSocket, since action_run_ws_handler
    calls the exact same three methods (.send_json/.receive_text/.close)."""

    def __init__(self, incoming: list | None = None):
        self.sent: list[dict] = []
        self.closed_code: int | None = None
        self._incoming = list(incoming or [])

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def receive_text(self) -> str:
        if self._incoming:
            return self._incoming.pop(0)
        raise WebSocketDisconnect(code=1000)

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code


async def _make_scenario(decision_tree=None, hidden_iocs=None) -> "Scenario":
    from app.db.session import AsyncSessionLocal
    from app.models.scenario import Scenario

    async with AsyncSessionLocal() as db:
        scenario = Scenario(
            id=str(uuid.uuid4()),
            title="WS Handler Test Scenario",
            source_type="manual",
            source_reference=f"TEST-WS-{uuid.uuid4().hex[:8]}",
            difficulty="practitioner",
            industry_vertical="energy",
            status="approved",
            decision_tree=decision_tree if decision_tree is not None else _FAST_DECISION_TREE,
            alert_sequence=[],
            hidden_iocs=hidden_iocs or [],
        )
        db.add(scenario)
        await db.commit()
        await db.refresh(scenario)
        return scenario


async def _start_live_run(scenario, user_id, seed=1, mode="scenario"):
    compiled = action_engine.compile_scenario(scenario, seed)
    run_id = str(uuid.uuid4())
    await action_run_store.start_run(run_id, user_id, scenario.id, mode, compiled)
    return run_id, compiled


async def test_connect_to_unknown_run_closes_with_4004():
    ws = FakeWebSocket()
    await action_run_ws_handler(ws, "not-a-real-run-id", "some-user")
    assert ws.closed_code == 4004
    assert ws.sent == []


async def test_connect_as_the_wrong_user_closes_with_4003():
    from tests.conftest import ensure_test_user_row
    await ensure_test_user_row("action-run-owner-1")
    scenario = await _make_scenario()
    run_id, _ = await _start_live_run(scenario, "action-run-owner-1")

    ws = FakeWebSocket()
    await action_run_ws_handler(ws, run_id, "some-other-user")
    assert ws.closed_code == 4003
    assert ws.sent == []

    # Cleanup — this run was never finalized by the handler (it was
    # rejected before that), so evict it directly to avoid leaking state
    # into other tests sharing the process-wide singleton store.
    async with action_run_store._lock:
        action_run_store._runs.pop(run_id, None)


async def test_fresh_connect_sends_a_run_resync_event_at_zero(request):
    from tests.conftest import ensure_test_user_row
    await ensure_test_user_row("action-run-owner-2")
    scenario = await _make_scenario()
    run_id, _ = await _start_live_run(scenario, "action-run-owner-2")

    ws = FakeWebSocket(incoming=[])  # disconnects immediately after resync
    await action_run_ws_handler(ws, run_id, "action-run-owner-2")

    assert ws.sent[0]["type"] == "run.resync"
    assert ws.sent[0]["elapsed_seconds"] == 0
    assert ws.sent[0]["attacker_clock_seconds"] == 0
    assert ws.sent[0]["cap_seconds"] == 600  # CAP_SECONDS_BY_MODE["scenario"]
    # Leak check: a run nobody has touched yet must resync to nothing —
    # no host, IOC, or edge exists to earn before the first verb.
    assert ws.sent[0]["hosts"] == []
    assert ws.sent[0]["revealed_iocs"] == []
    assert ws.sent[0]["edges"] == []


async def test_action_submit_returns_state_delta_and_clock_tick():
    from tests.conftest import ensure_test_user_row
    await ensure_test_user_row("action-run-owner-3")
    scenario = await _make_scenario()
    run_id, _ = await _start_live_run(scenario, "action-run-owner-3")

    ws = FakeWebSocket(incoming=[
        '{"type": "action.submit", "verb": "scan_network"}',
    ])
    await action_run_ws_handler(ws, run_id, "action-run-owner-3")

    types = [m["type"] for m in ws.sent]
    assert types[0] == "run.resync"
    assert "state.delta" in types
    assert "clock.tick" in types

    delta_event = next(m for m in ws.sent if m["type"] == "state.delta")
    assert "nodes" in delta_event["delta"]  # scan_network's own delta shape

    tick_event = next(m for m in ws.sent if m["type"] == "clock.tick")
    assert tick_event["elapsed_seconds"] == 45  # scan_network cost

    # The run is still live (scenario mode's 600s cap, 120s final-stage
    # trigger not yet reached with only one cheap verb spent) — clean up.
    async with action_run_store._lock:
        action_run_store._runs.pop(run_id, None)


async def test_invalid_verb_sends_an_error_and_does_not_advance_the_clock():
    from tests.conftest import ensure_test_user_row
    await ensure_test_user_row("action-run-owner-4")
    scenario = await _make_scenario()
    run_id, _ = await _start_live_run(scenario, "action-run-owner-4")

    ws = FakeWebSocket(incoming=[
        '{"type": "action.submit", "verb": "hack_the_mainframe"}',
    ])
    await action_run_ws_handler(ws, run_id, "action-run-owner-4")

    error_events = [m for m in ws.sent if m["type"] == "error"]
    assert len(error_events) == 1

    live = await action_run_store.get(run_id)
    assert live is not None
    assert live.run_state.elapsed_seconds == 0

    async with action_run_store._lock:
        action_run_store._runs.pop(run_id, None)


async def test_ping_receives_pong():
    from tests.conftest import ensure_test_user_row
    await ensure_test_user_row("action-run-owner-5")
    scenario = await _make_scenario()
    run_id, _ = await _start_live_run(scenario, "action-run-owner-5")

    ws = FakeWebSocket(incoming=['{"type": "ping"}'])
    await action_run_ws_handler(ws, run_id, "action-run-owner-5")

    assert any(m["type"] == "pong" for m in ws.sent)

    async with action_run_store._lock:
        action_run_store._runs.pop(run_id, None)


async def test_reconnect_resumes_the_existing_run_state_not_a_fresh_one():
    """The reconnect guarantee end to end: apply a verb (simulating a first
    connection's activity), then make a wholly separate handler call
    (simulating a fresh WS connection for the same run_id) and confirm the
    resync reflects the ALREADY-spent clock, not zero."""
    from tests.conftest import ensure_test_user_row
    await ensure_test_user_row("action-run-owner-6")
    scenario = await _make_scenario()
    run_id, _ = await _start_live_run(scenario, "action-run-owner-6")

    await action_run_store.apply_verb(run_id, "scan_network", None)

    ws = FakeWebSocket(incoming=[])
    await action_run_ws_handler(ws, run_id, "action-run-owner-6")

    assert ws.sent[0]["type"] == "run.resync"
    assert ws.sent[0]["elapsed_seconds"] == 45

    async with action_run_store._lock:
        action_run_store._runs.pop(run_id, None)


async def test_run_over_triggers_finalize_and_a_run_end_event():
    from tests.conftest import ensure_test_user_row
    await ensure_test_user_row("action-run-owner-7")
    scenario = await _make_scenario()
    run_id, compiled = await _start_live_run(scenario, "action-run-owner-7")

    final_stage = next(s for s in compiled.stages if s.is_final)
    target_host_id = final_stage.compromises_host_ids[0]

    # isolate (20s) + enough scan_network (45s each) to cross the +2m/120s
    # final-stage trigger: 20 + 3*45 = 155s >= 120s.
    ws = FakeWebSocket(incoming=[
        f'{{"type": "action.submit", "verb": "isolate", "target": "{target_host_id}"}}',
        '{"type": "action.submit", "verb": "scan_network"}',
        '{"type": "action.submit", "verb": "scan_network"}',
        '{"type": "action.submit", "verb": "scan_network"}',
    ])
    await action_run_ws_handler(ws, run_id, "action-run-owner-7")

    run_end_events = [m for m in ws.sent if m["type"] == "run.end"]
    assert len(run_end_events) == 1
    assert run_end_events[0]["outcome"] == "win"
    assert "score_breakdown" in run_end_events[0]

    # finalize() evicts on completion — the handler must not leave a
    # stale entry behind for a run that has already ended.
    assert await action_run_store.get(run_id) is None


# _place_iocs now binds hidden_iocs to the attack path (hosts a
# decision_gate stage actually compromises), not any host in the world —
# with only _FAST_DECISION_TREE's single gate, the attack path is exactly
# one host, so both entries below would land on the SAME host and this
# fixture's own "multiple hosts" premise would silently stop holding.
# This wider tree gives the attack path enough hosts (up to 3, shuffled
# per seed) for _place_iocs's own rng.choice to actually have room to
# scatter two IOCs onto different ones — verified empirically for this
# file's seed=1 by the assertion at the top of each test that uses it,
# not hand-derived from the RNG.
_MULTI_HOST_DECISION_TREE = [
    {"id": "gate-001", "trigger_timestamp": "+2m", "mitre_technique": "T1078",
     "context_summary": "Suspicious VPN activity.", "options": [], "correct_index": 0,
     "consequence_if_wrong": "Missed.", "rationale": "Correlate anomalies.", "nist_control_ref": "DE.AE-2"},
    {"id": "gate-002", "trigger_timestamp": "+8m", "mitre_technique": "T1003",
     "context_summary": "Credential dump detected.", "options": [], "correct_index": 1,
     "consequence_if_wrong": "Missed.", "rationale": "Preserve evidence.", "nist_control_ref": "RS.AN-3"},
    {"id": "gate-003", "trigger_timestamp": "+15m", "mitre_technique": "T1021",
     "context_summary": "Lateral movement detected.", "options": [], "correct_index": 0,
     "consequence_if_wrong": "Missed.", "rationale": "Contain spread.", "nist_control_ref": "RS.MI-1"},
]

# Two hidden_iocs deliberately bound to different hosts (via
# action_engine._place_iocs's seeded RNG, over the attack path
# _MULTI_HOST_DECISION_TREE above provides) — needed so
# test_resync_after_scan_and_query_returns_exactly_the_earned_subset can
# assert the OTHER host's IOC never leaks into a resync that only earned
# the first one.
_MULTI_HOST_HIDDEN_IOCS = [
    {"matches_on": {"ip": "185.220.101.34"}, "timestamp": "+1m", "severity": "medium",
     "source_system": "Auth", "rule_id": "AUTH-009", "description": "Same-IP login on legacy portal",
     "raw_log": "auth=success src_ip=185.220.101.34"},
    {"matches_on": {"hostname": "CORP-DC-01"}, "timestamp": "+7m", "severity": "medium",
     "source_system": "EDR", "rule_id": "EDR-030", "description": "LOLBin activity before credential dump",
     "raw_log": "proc=certutil.exe host=CORP-DC-01"},
]


async def test_resync_after_scan_and_query_returns_exactly_the_earned_subset():
    """The resync gap found during Item 5 planning: build_run_resync_event
    used to send only clocks, so a reconnecting player lost every host/IOC
    they'd already earned. A reconnect must restore exactly that — every
    revealed host (scan_network reveals all at once) and the full topology
    among them, but ONLY the IOCs actually discovered (query_logs on one
    specific host), never another host's still-undiscovered hidden_iocs."""
    from tests.conftest import ensure_test_user_row
    await ensure_test_user_row("action-run-owner-8")
    scenario = await _make_scenario(decision_tree=_MULTI_HOST_DECISION_TREE, hidden_iocs=_MULTI_HOST_HIDDEN_IOCS)
    run_id, compiled = await _start_live_run(scenario, "action-run-owner-8")

    queried_placement = compiled.ioc_placements[0]
    other_placements = [p for p in compiled.ioc_placements if p.host_id != queried_placement.host_id]
    assert other_placements, "fixture must place IOCs on more than one host for this test to mean anything"

    await action_run_store.apply_verb(run_id, "scan_network", None)
    await action_run_store.apply_verb(run_id, "query_logs", queried_placement.host_id)

    # Reconnect: a wholly separate handler call, simulating a fresh WS
    # connection resuming this run_id (same pattern as
    # test_reconnect_resumes_the_existing_run_state_not_a_fresh_one).
    ws = FakeWebSocket(incoming=[])
    await action_run_ws_handler(ws, run_id, "action-run-owner-8")

    resync = ws.sent[0]
    assert resync["type"] == "run.resync"

    resynced_host_ids = {h["id"] for h in resync["hosts"]}
    assert resynced_host_ids == {h.id for h in compiled.world.hosts}  # scan_network revealed all

    assert resync["edges"] == [e.to_dict() for e in compiled.edges]  # full topology once all hosts revealed

    resynced_rule_ids = {ioc["rule_id"] for ioc in resync["revealed_iocs"]}
    assert queried_placement.rule_id in resynced_rule_ids
    for other in other_placements:
        assert other.rule_id not in resynced_rule_ids  # never leak an undiscovered host's IOC

    async with action_run_store._lock:
        action_run_store._runs.pop(run_id, None)


async def test_block_ip_correct_guess_includes_the_matched_ioc_body_live_and_on_resync():
    """QA-review-flagged asymmetry, live on PR #8: a correct block_ip adds
    its matched IOC to discovered_ioc_keys (so any later resync's
    earned_state_snapshot already includes its full body), but the LIVE
    delta used to send only {"correct": True, "host_id": ...} — a
    reconnecting player would see IOC content the live delta never
    actually showed them. Confirmed not a leak (the key is genuinely
    earned the instant the correct IP is blocked — verb_engine.py's own
    apply_verb already records it as discovered), just an inconsistency:
    the live delta was under-reporting evidence it had already credited.
    Fixed for parity — block_ip's delta now includes the same
    revealed_iocs entry a resync would. This test asserts parity
    directly: live and resync must show IDENTICAL content, not just that
    content exists somewhere."""
    from tests.conftest import ensure_test_user_row
    await ensure_test_user_row("action-run-owner-9")
    scenario = await _make_scenario(decision_tree=_MULTI_HOST_DECISION_TREE, hidden_iocs=_MULTI_HOST_HIDDEN_IOCS)
    run_id, compiled = await _start_live_run(scenario, "action-run-owner-9")

    ip_placement = next(p for p in compiled.ioc_placements if p.matches_on.get("ip"))

    ws = FakeWebSocket(incoming=[
        f'{{"type": "action.submit", "verb": "block_ip", "target": "{ip_placement.matches_on["ip"]}"}}',
    ])
    await action_run_ws_handler(ws, run_id, "action-run-owner-9")

    delta_event = next(m for m in ws.sent if m["type"] == "state.delta")
    assert delta_event["delta"]["correct"] is True
    assert delta_event["delta"]["host_id"] == ip_placement.host_id
    live_iocs = delta_event["delta"]["revealed_iocs"]
    assert len(live_iocs) == 1
    assert live_iocs[0]["rule_id"] == ip_placement.rule_id
    assert live_iocs[0]["description"] == ip_placement.description

    # Reconnect: a wholly separate handler call, simulating a fresh WS
    # connection resuming this run_id.
    ws2 = FakeWebSocket(incoming=[])
    await action_run_ws_handler(ws2, run_id, "action-run-owner-9")
    resync = ws2.sent[0]
    assert resync["type"] == "run.resync"
    resync_iocs = [i for i in resync["revealed_iocs"] if i["rule_id"] == ip_placement.rule_id]
    assert len(resync_iocs) == 1

    # Parity: identical content live and on resync, not just presence —
    # this is the actual asymmetry the review caught.
    assert live_iocs[0] == resync_iocs[0]

    async with action_run_store._lock:
        action_run_store._runs.pop(run_id, None)
