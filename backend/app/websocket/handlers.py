import asyncio
import json
import logging
import uuid
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select, text
from app.db.session import AsyncSessionLocal
from app.models.session import SimulationSession, SessionParticipant, SessionDecision
from app.models.scenario import Scenario
from app.models.user import User
from app.models.arena import ArenaMatch, ArenaAction
from app.websocket.manager import (
    manager,
    build_alert_event,
    build_decision_gate_event,
    build_system_event,
    build_investigation_result_event,
)
from app.pipeline.claude_client import generate_decision_commentary
from app.services.siem_service import send_alert_to_siem, send_decision_to_siem
from app.services.org_simulation import (
    ORG_ARCHETYPES,
    ATTACKER_ACTION_TYPES,
    DEFENDER_ACTION_TYPES,
    apply_attacker_action,
    apply_defender_action,
    replay,
    _derive_rng,
)

logger = logging.getLogger(__name__)

# Fields the investigation panel (Phase 3) can pivot on. Values are matched against
# each hidden IOC's `matches_on` dict first (exact field match), falling back to a
# case-insensitive substring match over `raw_log`/`description` so hidden entries
# authored without an explicit `matches_on` entry are still findable.
INVESTIGATE_FIELDS = {"ip", "hostname", "username", "process_name"}


def _match_hidden_iocs(hidden_iocs: list, field: str, value: str) -> list:
    """Return hidden IOC dicts matching the query field/value.

    Match strategy (simple field-equality/substring — no full-text search engine,
    per Phase 3 anti-pattern guard):
    1. Exact (case-insensitive) match against the entry's own `matches_on[field]`.
    2. Fallback: case-insensitive substring match of `value` in the entry's
       `raw_log` or `description`, so entries without a `matches_on` still surface.
    """
    needle = value.strip().lower()
    matches = []
    for entry in hidden_iocs:
        matches_on = entry.get("matches_on") or {}
        tagged_value = matches_on.get(field)
        if tagged_value and needle == str(tagged_value).strip().lower():
            matches.append(entry)
            continue

        haystack = f"{entry.get('raw_log', '')} {entry.get('description', '')}".lower()
        if needle and needle in haystack:
            matches.append(entry)
    return matches


async def simulation_ws_handler(websocket: WebSocket, session_id: str, user_id: str):
    await manager.connect(session_id, websocket)

    # 1. Fetch user profile and participant role to automatically add to presence list
    async with AsyncSessionLocal() as db:
        user_res = await db.execute(select(User).where(User.id == user_id))
        user = user_res.scalar_one_or_none()
        p_res = await db.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id
            )
        )
        participant = p_res.scalar_one_or_none()

    role = participant.role if participant else "soc_analyst"
    name = user.full_name or user.email if user else "Analyst"

    await manager.add_user_presence(session_id, user_id, name, role, websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send_personal(websocket, build_system_event("error", {"detail": "Invalid JSON"}))
                continue

            msg_type = msg.get("type")

            if msg_type == "chat":
                await manager.broadcast(session_id, {
                    "type": "chat",
                    "user_id": user_id,
                    "name": name,
                    "role": role,
                    "text": msg.get("text", "")[:2000],
                })

            elif msg_type == "ping":
                await manager.send_personal(websocket, build_system_event("pong"))

            elif msg_type == "submit_vote":
                option_idx = msg.get("chosen_option_index")
                if option_idx is not None:
                    manager.record_vote(session_id, user_id, option_idx)
                    await manager.broadcast_vote_state(session_id)

            elif msg_type == "submit_command_decision":
                # Ensure only Incident Commander (Host) can lock in decisions
                if role != "incident_commander":
                    await manager.send_personal(websocket, build_system_event("error", {"detail": "Only the Incident Commander can finalize decisions"}))
                    continue

                option_idx = msg.get("chosen_option_index")
                gate_id = msg.get("decision_gate_id")

                async with AsyncSessionLocal() as db:
                    s_res = await db.execute(select(SimulationSession).where(SimulationSession.id == session_id))
                    session = s_res.scalar_one_or_none()
                    if not session or session.status != "active":
                        await manager.send_personal(websocket, build_system_event("error", {"detail": "Session is not active"}))
                        continue

                    sc_res = await db.execute(select(Scenario).where(Scenario.id == session.scenario_id))
                    scenario = sc_res.scalar_one_or_none()

                    decision_tree = scenario.decision_tree or []
                    gate = next((g for g in decision_tree if g.get("id") == gate_id), None)
                    if not gate:
                        await manager.send_personal(websocket, build_system_event("error", {"detail": "Decision gate not found"}))
                        continue

                    is_correct = option_idx == gate["correct_index"]
                    consequence = gate["consequence_if_wrong"] if not is_correct else gate.get("consequence_if_correct", "Good call.")

                    decision = SessionDecision(
                        session_id=session_id,
                        user_id=user_id,
                        decision_gate_id=gate_id,
                        chosen_option_index=option_idx,
                        is_correct=is_correct,
                        response_time_seconds=msg.get("response_time_seconds"),
                        consequence_applied=consequence,
                        nist_control_ref=gate.get("nist_control_ref"),
                        mitre_technique=gate.get("mitre_technique"),
                    )
                    db.add(decision)
                    session.decisions_made += 1
                    if is_correct:
                        session.decisions_correct += 1
                    await db.commit()

                manager.clear_votes(session_id)
                await manager.broadcast(session_id, {
                    "type": "decision_result",
                    "decision_gate_id": gate_id,
                    "is_correct": is_correct,
                    "rationale": gate["rationale"],
                    "consequence_applied": consequence,
                    "correct_index": gate["correct_index"],
                })
                # Resume simulation alert flow
                manager.resume_session(session_id)

                # Dispatch gate decision to org's SIEM (fire-and-forget)
                _siem_org_id = session.organization_id or session.host_user_id
                _siem_decision = {
                    "gate_id": gate_id,
                    "chosen_option_text": gate["options"][option_idx]["text"] if option_idx < len(gate["options"]) else "",
                    "is_correct": is_correct,
                    "score_impact": 1 if is_correct else -1,
                }
                asyncio.create_task(send_decision_to_siem(
                    _siem_org_id,
                    _siem_decision,
                    scenario.title if scenario else "Unknown",
                ))

                # Fire AI facilitator commentary asynchronously (non-blocking)
                asyncio.create_task(_broadcast_ai_commentary(
                    session_id=session_id,
                    scenario_title=scenario.title if scenario else "Unknown",
                    gate_id=gate_id,
                    team_choice=gate["options"][option_idx]["text"] if option_idx < len(gate["options"]) else "",
                    correct_choice=gate["options"][gate["correct_index"]]["text"] if gate["options"] else "",
                    is_correct=is_correct,
                    mitre_technique=gate.get("mitre_technique", ""),
                    nist_ref=gate.get("nist_control_ref", ""),
                ))

            elif msg_type == "toggle_simulation_pause":
                if role != "incident_commander":
                    await manager.send_personal(websocket, build_system_event("error", {"detail": "Only the Incident Commander can pause/resume simulations"}))
                    continue

                if manager.is_paused(session_id):
                    manager.resume_session(session_id)
                    await manager.broadcast(session_id, build_system_event("simulation_resumed"))
                else:
                    manager.pause_session(session_id)
                    await manager.broadcast(session_id, build_system_event("simulation_paused"))

            elif msg_type == "inject_alert":
                if role != "incident_commander":
                    await manager.send_personal(websocket, build_system_event("error", {"detail": "Only the Incident Commander can inject custom alerts"}))
                    continue

                alert_payload = msg.get("alert")
                if alert_payload:
                    manager.queue_inject_alert(session_id, alert_payload)
                    await manager.broadcast(session_id, {
                        "type": "alert_injected",
                        "payload": alert_payload
                    })

            elif msg_type == "stream_alerts":
                if role != "incident_commander":
                    await manager.send_personal(websocket, build_system_event("error", {"detail": "Only the Incident Commander can start the alert stream"}))
                    continue
                if manager.start_streaming(session_id):
                    asyncio.create_task(_stream_alerts(session_id, user_id))

            elif msg_type == "investigate_query":
                field = msg.get("field")
                value = msg.get("value")

                if field not in INVESTIGATE_FIELDS or not isinstance(value, str) or not value:
                    await manager.send_personal(websocket, build_system_event(
                        "error",
                        {"detail": f"investigate_query requires 'field' (one of {sorted(INVESTIGATE_FIELDS)}) and a non-empty string 'value'"},
                    ))
                    continue

                try:
                    async with AsyncSessionLocal() as db:
                        s_res = await db.execute(select(SimulationSession).where(SimulationSession.id == session_id))
                        session = s_res.scalar_one_or_none()
                        if not session:
                            await manager.send_personal(websocket, build_system_event("error", {"detail": "Session not found"}))
                            continue

                        sc_res = await db.execute(select(Scenario).where(Scenario.id == session.scenario_id))
                        scenario = sc_res.scalar_one_or_none()

                        hidden_iocs = (scenario.hidden_iocs if scenario else None) or []
                        matches = _match_hidden_iocs(hidden_iocs, field, value)

                        log_entry = {
                            "user_id": user_id,
                            "field": field,
                            "value": value,
                            "match_count": len(matches),
                            "found": len(matches) > 0,
                            "queried_at": datetime.utcnow().isoformat(),
                        }
                        # Atomic JSONB append at the SQL level — avoids the lost-update race
                        # from a Python-side read-modify-write when multiple players in the
                        # same session pivot concurrently (each WS message uses its own
                        # AsyncSessionLocal, so two concurrent commits could otherwise clobber
                        # each other's log entry).
                        await db.execute(
                            text(
                                "UPDATE simulation_sessions "
                                "SET investigation_log = investigation_log || CAST(:entry AS jsonb) "
                                "WHERE id = :session_id"
                            ),
                            {"entry": json.dumps([log_entry]), "session_id": session.id},
                        )
                        await db.commit()

                    await manager.send_personal(
                        websocket,
                        build_investigation_result_event(field, value, matches),
                    )
                except Exception:
                    logger.exception(
                        "Unexpected error handling investigate_query for session %s (field=%s)",
                        session_id, field,
                    )
                    await manager.send_personal(websocket, build_system_event(
                        "error",
                        {"detail": "Failed to process investigation query"},
                    ))

    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)
        await manager.remove_user_presence(session_id, user_id)
        # Persist disconnected state so audit logs and admin dashboards reflect reality
        try:
            async with AsyncSessionLocal() as db:
                p_res = await db.execute(
                    select(SessionParticipant).where(
                        SessionParticipant.session_id == session_id,
                        SessionParticipant.user_id == user_id,
                    )
                )
                participant = p_res.scalar_one_or_none()
                if participant:
                    participant.is_connected = False
                    await db.commit()
        except Exception:
            pass  # non-fatal — presence broadcast already sent the correct in-memory state


async def _broadcast_ai_commentary(
    session_id: str,
    scenario_title: str,
    gate_id: str,
    team_choice: str,
    correct_choice: str,
    is_correct: bool,
    mitre_technique: str,
    nist_ref: str,
) -> None:
    """Call Claude for real-world context and broadcast it as an AI facilitator chat message."""
    try:
        commentary = await asyncio.to_thread(
            generate_decision_commentary,
            scenario_title, gate_id, team_choice, correct_choice,
            is_correct, mitre_technique, nist_ref,
        )
        if commentary:
            await manager.broadcast(session_id, {
                "type": "ai_commentary",
                "gate_id": gate_id,
                "text": commentary,
                "is_correct": is_correct,
            })
    except Exception:
        logger.exception("Failed to generate or broadcast AI commentary for session %s gate %s", session_id, gate_id)


async def _stream_alerts(session_id: str, requester_id: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SimulationSession).where(SimulationSession.id == session_id))
        session = result.scalar_one_or_none()
        if not session or session.host_user_id != requester_id:
            return

        s_result = await db.execute(select(Scenario).where(Scenario.id == session.scenario_id))
        scenario = s_result.scalar_one_or_none()
        if not scenario:
            return

        alerts = scenario.alert_sequence or []
        siem_org_id = session.organization_id or session.host_user_id
        scenario_title = scenario.title or "Unknown Scenario"

        if not alerts:
            await manager.broadcast(
                session_id,
                build_system_event("error", {"detail": "This scenario has no alert sequence yet. Re-ingest the source document to regenerate it."}),
            )
            manager.stop_streaming(session_id)
            return

        gates_by_trigger = {}
        for gate in (scenario.decision_tree or []):
            ts = gate["trigger_timestamp"]
            if ts in gates_by_trigger:
                logger.warning(
                    "Scenario %s has duplicate decision gate trigger_timestamp '%s' — gate '%s' will be skipped",
                    session.scenario_id, ts, gate.get("id"),
                )
            else:
                gates_by_trigger[ts] = gate

        # Index pressure injections by trigger timestamp
        injections_by_trigger: dict = {}
        for inj in (scenario.pressure_injections or []):
            ts = inj.get("trigger_timestamp")
            if ts:
                injections_by_trigger.setdefault(ts, []).append(inj)

        total = len(alerts)
        speed = session.speed_multiplier or 1.0

        try:
            for i, alert in enumerate(alerts):
                # Pause synchronization checkpoint
                await manager.get_pause_event(session_id).wait()

                # Process any facilitator injected alerts
                injected = manager.pop_injected_alerts(session_id)
                for inj_alert in injected:
                    await manager.broadcast(session_id, build_alert_event(inj_alert, -1, total))
                    await asyncio.sleep(2.0 / speed)

                # Broadcast standard alert
                await manager.broadcast(session_id, build_alert_event(alert, i, total))

                # Dispatch alert to org's SIEM (fire-and-forget — never blocks simulation)
                asyncio.create_task(send_alert_to_siem(siem_org_id, alert, scenario_title))

                alert_ts = alert.get("timestamp")

                # Fire pressure injections at this timestamp (before gate pause so they overlap)
                for pressure_inj in injections_by_trigger.get(alert_ts, []):
                    await manager.broadcast(session_id, {
                        "type": "pressure_injection",
                        "payload": pressure_inj,
                    })
                    await asyncio.sleep(1.0 / speed)

                # Autopause simulation on decision gate
                if alert_ts in gates_by_trigger:
                    gate = gates_by_trigger[alert_ts]
                    manager.clear_votes(session_id)
                    await manager.broadcast(session_id, build_decision_gate_event(gate))
                    manager.pause_session(session_id)
                    await manager.broadcast(session_id, build_system_event("simulation_paused"))
                    await asyncio.sleep(0)

                interval = 3.0 / speed
                await asyncio.sleep(interval)

            # Final check for last-second injections
            await manager.get_pause_event(session_id).wait()
            injected = manager.pop_injected_alerts(session_id)
            for inj_alert in injected:
                await manager.broadcast(session_id, build_alert_event(inj_alert, -1, total))

            await manager.broadcast(session_id, build_system_event("simulation_complete"))
        finally:
            manager.stop_streaming(session_id)


# ── Live Arena Mode (Phase C) — live match orchestration ────────────────────
#
# Design notes (see docs/plans/live-arena-mode.md, Phase C):
#
# 1. State reconstruction: every attacker_action/defender_action message
#    reconstructs current OrgState by calling org_simulation.replay() over
#    ALL persisted ArenaAction rows for the match, then applies the new
#    action against that result. This is deliberately the simple, always-
#    correct choice over an in-memory per-match state cache: replay() is a
#    pure, cheap, in-process function operating on a small (~8-15 host) org,
#    so the perf cost of recomputing it per message is negligible at this
#    phase's scale, and it structurally CANNOT drift from what replay()
#    would independently produce (the plan's single most important
#    invariant) because it IS replay(), called fresh every time. A cache
#    can be introduced later purely as a perf optimization once/if match
#    volume justifies it — it would need to be invalidated/rebuilt with the
#    exact same care taken here, so deferring it avoids a whole class of
#    cache-invalidation bugs for now.
#
# 2. sequence_number race prevention: an asyncio.Lock per match_id, held
#    by ConnectionManager (manager.get_arena_match_lock(match_id)), wraps
#    the "read current action count, then insert the next ArenaAction row"
#    critical section. This works because a single backend process handles
#    all WS connections in this deployment (same assumption the existing
#    ConnectionManager already relies on for its in-memory presence/vote/
#    pause state) — an in-process lock is sufficient to serialise it, and
#    simpler than a SQL-level atomic sequence/COALESCE(MAX()+1) pattern.
#    The model's UniqueConstraint("match_id", "sequence_number") remains as
#    a defensive backstop: if this invariant is ever violated (e.g. a
#    future multi-process deployment), a concurrent double-insert raises a
#    DB integrity error instead of silently corrupting the action log.

ARENA_ROLES = ("attacker", "defender")

# Response-option template library for arena decision gates — parameterized
# by the actual affected host/credential/segment from the triggering action's
# payload, never pre-authored per-scenario JSON. Mirrors the plan's
# "contain/isolate/monitor/escalate" vocabulary and reuses
# build_decision_gate_event's existing shape (gate id/context_summary/
# options) so SimulationRoomPage.tsx's existing decision_gate rendering
# works unchanged.
#
# Each entry's `payload_fields` lists exactly which ID(s) that
# response_action_type needs (per apply_defender_action's real payload
# contract in org_simulation.py) — an option is only offered when every ID
# it needs is actually available, so a defender is never shown a button
# whose click would silently no-op.
_ARENA_RESPONSE_OPTIONS = [
    {"text": "Isolate the affected host", "response_action_type": "isolate_host", "payload_fields": ("host_id",)},
    {"text": "Disable the compromised credential", "response_action_type": "disable_credential", "payload_fields": ("credential_id",)},
    {"text": "Increase monitoring on the affected segment", "response_action_type": "increase_monitoring", "payload_fields": ("segment_id",)},
    {"text": "Monitor and gather more evidence before acting", "response_action_type": "acknowledge", "payload_fields": ()},
]


def _build_arena_decision_gate(reason: str, host: dict | None, credential_id: str | None, sequence_number: int) -> dict:
    """Build a decision_gate-shaped dict (matching Scenario.decision_tree's
    gate shape: id/context_summary/options) from a small template library,
    parameterized by the real affected host/credential/segment — not
    pre-authored JSON. Passed straight into the existing
    build_decision_gate_event() helper so the wire shape is byte-identical
    to scripted scenarios."""
    host_desc = f"{host['hostname']} ({host['role']})" if host else "an affected host"
    available_ids = {
        "host_id": host["id"] if host else None,
        "credential_id": credential_id,
        "segment_id": host.get("network_segment_id") if host else None,
    }
    options = []
    for opt in _ARENA_RESPONSE_OPTIONS:
        needed = opt["payload_fields"]
        if any(available_ids.get(field) is None for field in needed):
            continue  # this option's required ID isn't known here — don't offer a dead button
        entry = {"text": opt["text"], "response_action_type": opt["response_action_type"]}
        entry.update({field: available_ids[field] for field in needed})
        options.append(entry)
    return {
        "id": f"arena-gate-{sequence_number}-{uuid.uuid4().hex[:8]}",
        "context_summary": f"{reason} — {host_desc}.",
        "options": options,
    }


def _decision_gate_trigger(action_type: str, payload: dict, prev_state, new_state) -> tuple[str, dict | None, str | None] | None:
    """Decide whether an attacker action just crossed a decision-gate
    threshold. Returns (reason, host_dict_or_None, credential_id_or_None)
    or None if no gate should fire. Kept intentionally small per Phase C's
    scope (a minimal, legible trigger set — not an elaborate rules engine)."""
    if action_type == "deploy_impact":
        host_id = payload.get("host_id")
        host = new_state.get_host(host_id)
        return ("Impact activity in progress", host.to_dict() if host else None, None)

    if action_type in ("escalate_privilege", "lateral_move"):
        host_id = payload.get("target_host_id") or payload.get("host_id")
        prev_host = prev_state.get_host(host_id) if host_id else None
        new_host = new_state.get_host(host_id) if host_id else None
        if new_host and new_host.compromise_level in ("admin", "domain_admin"):
            if not prev_host or prev_host.compromise_level != new_host.compromise_level:
                credential_id = payload.get("credential_id")
                return (
                    f"Host reached {new_host.compromise_level.replace('_', ' ')}-level compromise",
                    new_host.to_dict(),
                    credential_id,
                )
    return None


async def _load_match_and_actions(db, match_id: str):
    """Fetch the ArenaMatch row plus its ordered ArenaAction rows, as plain
    dicts ready for org_simulation.replay()."""
    m_res = await db.execute(select(ArenaMatch).where(ArenaMatch.id == match_id))
    match = m_res.scalar_one_or_none()
    if not match:
        return None, []
    a_res = await db.execute(
        select(ArenaAction).where(ArenaAction.match_id == match_id).order_by(ArenaAction.sequence_number)
    )
    rows = a_res.scalars().all()
    action_dicts = [
        {
            "sequence_number": a.sequence_number,
            "actor": a.actor,
            "action_type": a.action_type,
            "payload": a.payload,
        }
        for a in rows
    ]
    return match, action_dicts


async def _persist_arena_action(db, match_id: str, actor: str, action_type: str, payload: dict, existing_count: int) -> ArenaAction:
    """Insert the next ArenaAction row for a match. Caller MUST hold
    manager.get_arena_match_lock(match_id) for the whole
    read-count-then-insert critical section — this function only does the
    insert half, using the count the caller already computed under the
    lock, so sequence_number assignment can't race across concurrent WS
    messages for the same match."""
    action = ArenaAction(
        id=str(uuid.uuid4()),
        match_id=match_id,
        sequence_number=existing_count,
        actor=actor,
        action_type=action_type,
        payload=payload,
        created_at=datetime.utcnow(),
    )
    db.add(action)
    await db.commit()
    return action


def _role_for_user(match: ArenaMatch, user_id: str) -> str | None:
    if match.attacker_user_id == user_id:
        return "attacker"
    if match.defender_user_id == user_id:
        return "defender"
    return None


async def _execute_arena_action(match_id: str, role: str, action_type: str, payload: dict) -> dict | None:
    """The ONE critical section for applying + persisting an arena action —
    human or bot, attacker or defender. Both `arena_ws_handler`'s
    `attacker_action`/`defender_action` message branch AND the Phase D bot
    driver loop (`_run_arena_attacker_bot`) call this exact function so
    there is exactly one place that touches the lock, the DB write, and the
    match-completion check. Do not duplicate this logic anywhere else.

    Returns None if the match doesn't exist or isn't in a playable state
    (nothing was persisted). Otherwise returns a result dict:
    `{sequence_number, prev_state, new_state, detected, alert,
    match_completed}` — callers use this to drive their own
    notification/broadcast side effects (which deliberately stay OUTSIDE
    this function/the lock, exactly as Phase C's original inline version
    did, since sending over the wire shouldn't hold up the next action's
    critical section).
    """
    lock = manager.get_arena_match_lock(match_id)
    async with lock:
        async with AsyncSessionLocal() as db:
            match, action_dicts = await _load_match_and_actions(db, match_id)
            if not match:
                return None
            if match.status not in ("active", "lobby"):
                return None

            prev_state, _ = replay(match.seed, match.archetype_key, action_dicts)
            sequence_number = len(action_dicts)

            if role == "attacker":
                rng = _derive_rng(match.seed, sequence_number)
                action_for_engine = {"action_type": action_type, "payload": payload, "sequence_number": sequence_number}
                new_state, detected, alert = apply_attacker_action(prev_state, action_for_engine, rng)
            else:
                action_for_engine = {"action_type": action_type, "payload": payload}
                new_state = apply_defender_action(prev_state, action_for_engine)
                detected, alert = False, None

            await _persist_arena_action(db, match_id, role, action_type, payload, existing_count=sequence_number)

            # Match completion check (minimal per Phase C scope — only the
            # attacker-wins-on-impact condition; a defender-side win
            # condition is Phase H's job).
            match_completed = False
            if new_state.global_flags.get("impact_deployed") and match.status != "attacker_won":
                m_res = await db.execute(select(ArenaMatch).where(ArenaMatch.id == match_id))
                m = m_res.scalar_one_or_none()
                if m and m.status not in ("attacker_won", "defender_won", "abandoned"):
                    m.status = "attacker_won"
                    m.completed_at = datetime.utcnow()
                    m.final_org_state_cache = new_state.to_dict()
                    await db.commit()
                match_completed = True

    return {
        "sequence_number": sequence_number,
        "prev_state": prev_state,
        "new_state": new_state,
        "detected": detected,
        "alert": alert,
        "match_completed": match_completed,
    }


async def _notify_arena_action_result(match_id: str, role: str, action_type: str, payload: dict, result: dict) -> None:
    """Post-persistence notification side effects for one arena action —
    shared by the human WS path and the bot driver loop. Deliberately
    separate from `_execute_arena_action` (which only does the locked
    read-compute-persist critical section) so sending over the wire never
    holds up the next action's critical section, exactly as Phase C's
    original inline version behaved."""
    sequence_number = result["sequence_number"]
    prev_state = result["prev_state"]
    new_state = result["new_state"]
    detected = result["detected"]
    alert = result["alert"]

    if role == "attacker":
        attacker_ws = manager.get_arena_connection(match_id, "attacker")
        if attacker_ws:
            confirm = build_system_event("action_result", {
                "action_type": action_type,
                "sequence_number": sequence_number,
                "detected": detected,
            })
            await manager.send_personal(attacker_ws, confirm)

        if detected and alert:
            defender_ws = manager.get_arena_connection(match_id, "defender")
            if defender_ws:
                await manager.send_personal(defender_ws, build_alert_event(alert, sequence_number, sequence_number + 1))

        gate_trigger = _decision_gate_trigger(action_type, payload, prev_state, new_state)
        if gate_trigger:
            reason, host_dict, credential_id = gate_trigger
            gate = _build_arena_decision_gate(reason, host_dict, credential_id, sequence_number)
            defender_ws = manager.get_arena_connection(match_id, "defender")
            if defender_ws:
                await manager.send_personal(defender_ws, build_decision_gate_event(gate))
    else:
        # defender_action: confirm the effect back to the defender
        # (decision_result-equivalent — same wire shape family the
        # frontend already understands for scripted decision gates).
        defender_ws = manager.get_arena_connection(match_id, "defender")
        if defender_ws:
            await manager.send_personal(defender_ws, {
                "type": "decision_result",
                "decision_gate_id": None,
                "is_correct": True,
                "rationale": f"{action_type.replace('_', ' ').title()} applied.",
                "consequence_applied": f"{action_type} executed against the live org state.",
                "correct_index": None,
                "action_type": action_type,
                "payload": payload,
                "sequence_number": sequence_number,
            })

    if result["match_completed"]:
        result_event = build_system_event("match_complete", {
            "status": "attacker_won",
            "sequence_number": sequence_number,
        })
        attacker_ws = manager.get_arena_connection(match_id, "attacker")
        defender_ws = manager.get_arena_connection(match_id, "defender")
        if attacker_ws:
            await manager.send_personal(attacker_ws, result_event)
        if defender_ws:
            await manager.send_personal(defender_ws, result_event)


# ── Live Arena Mode (Phase D) — AI attacker policy bot driver ───────────────
#
# Design notes (see docs/plans/live-arena-mode.md, Phase D):
#
# Integration point chosen: the bot loop is started from arena_ws_handler,
# at connection-open time, for `human_defends_vs_ai` matches once the match
# is (or becomes) "active" — mirroring _stream_alerts' existing convention
# of starting background work in response to a live WS connection event,
# not at REST-create time (POST /arena/matches creates the match in
# "lobby" status with no one watching yet — spawning a bot loop against a
# match nobody has connected to would burn cycles for no visible benefit,
# and there is no defender websocket to notify anyway until the defender
# connects). manager.arena_bot_running (a plain in-process set, guarded by
# the same per-match asyncio.Lock used for action persistence) ensures at
# most one bot task is ever spawned per match even if the defender's
# connection drops and reconnects.
#
# Difficulty is not yet a field on ArenaMatch/CreateMatchRequest (out of
# this phase's explicit scope — Phase D only asked for the policy + driver,
# not new schema). A default of "medium" is used until a future phase wires
# a real difficulty selector through match creation.
_DEFAULT_BOT_DIFFICULTY = "medium"

# Pacing between bot moves — mirrors _stream_alerts' `interval = 3.0 /
# speed_multiplier` convention (handlers.py) so bot play feels like a real
# opponent instead of spamming actions instantly. No speed_multiplier
# concept exists for arena matches yet, so this is a fixed, realistic pace.
_BOT_MOVE_INTERVAL_SECONDS = 3.0

# Hard ceiling as defense-in-depth. The loop is finite-by-construction (the
# candidate builders in arena_ai_attacker.py filter out no-ops, and defender
# actions are one-directional, so the pool provably empties) — this cap
# never fires in practice (empirically 8-12 steps per match), it just bounds
# worst-case resource use if that invariant is ever violated by a future
# change, rather than relying solely on proof-by-construction.
_MAX_BOT_STEPS = 300


async def _run_arena_attacker_bot(match_id: str, difficulty: str = _DEFAULT_BOT_DIFFICULTY) -> None:
    """Drive the AI attacker side of a `human_defends_vs_ai` arena match to
    completion, calling `arena_ai_attacker.choose_attacker_action` for each
    move and submitting it through the EXACT SAME `_execute_arena_action` /
    `_notify_arena_action_result` path a human's `attacker_action` WS
    message uses — no parallel persistence logic. Stops when the match
    reaches a terminal status, the bot has no viable action, the defender's
    connection is gone, or `_MAX_BOT_STEPS` is reached."""
    from app.services.arena_ai_attacker import choose_attacker_action

    try:
        bot_moves_made = 0
        while bot_moves_made < _MAX_BOT_STEPS:
            async with AsyncSessionLocal() as db:
                match, action_dicts = await _load_match_and_actions(db, match_id)
            if not match or match.status not in ("active", "lobby"):
                return

            state, _ = replay(match.seed, match.archetype_key, action_dicts)
            rng = _derive_rng(match.seed, len(action_dicts))
            action = choose_attacker_action(state, difficulty, rng, actions_taken=bot_moves_made)
            if action is None:
                return  # bot has no viable move left — nothing more to do

            action_type = action.get("action_type")
            payload = action.get("payload") or {}

            result = await _execute_arena_action(match_id, "attacker", action_type, payload)
            if result is None:
                return  # match ended/vanished between the read above and the attempt
            bot_moves_made += 1

            try:
                await _notify_arena_action_result(match_id, "attacker", action_type, payload, result)
            except Exception:
                # Routine: the defender closed their tab/browser mid-match.
                # A dead socket's send_json can raise several exception
                # types depending on connection state (WebSocketDisconnect,
                # RuntimeError, etc. — see ConnectionManager.broadcast()'s
                # identical broad catch for the same reason), so catch
                # broadly here too. The action is already persisted (this
                # only affects the live notify), so just stop the bot
                # quietly instead of logging a full stack trace for an
                # expected event.
                logger.info("Arena bot stopping for match %s: defender connection appears gone", match_id)
                return

            if result["match_completed"]:
                return

            await asyncio.sleep(_BOT_MOVE_INTERVAL_SECONDS)
        else:
            logger.warning(
                "Arena bot for match %s hit the %d-step safety cap without reaching a terminal "
                "state — this should not happen given the candidate pool's finite-by-construction "
                "design; investigate if seen in practice.",
                match_id, _MAX_BOT_STEPS,
            )
    except Exception:
        logger.exception("Arena attacker bot loop crashed for match %s", match_id)
    finally:
        manager.arena_bot_running.discard(match_id)


def _maybe_start_arena_attacker_bot(match_id: str, mode: str) -> None:
    """Start the AI attacker bot loop for this match if it's a
    human_defends_vs_ai match and no bot task is already running for it.
    Safe to call every time a defender's WS connection opens (e.g. on
    reconnect) — the manager.arena_bot_running guard makes this idempotent."""
    if mode != "human_defends_vs_ai":
        return
    if match_id in manager.arena_bot_running:
        return
    manager.arena_bot_running.add(match_id)
    asyncio.create_task(_run_arena_attacker_bot(match_id))


async def arena_ws_handler(websocket: WebSocket, match_id: str, user_id: str):
    """Live Arena Mode match connection. One socket per (match, user); the
    user's role (attacker/defender) is resolved from ArenaMatch.
    attacker_user_id / defender_user_id. Phase D adds the AI attacker bot
    loop for human_defends_vs_ai matches (started below, once the match is
    active) — the bot calls the same apply_attacker_action/
    apply_defender_action functions via _execute_arena_action, the identical
    critical section a human's WS message uses."""
    async with AsyncSessionLocal() as db:
        match, _ = await _load_match_and_actions(db, match_id)
        if not match:
            await websocket.close(code=4004)
            return
        role = _role_for_user(match, user_id)
        if role is None:
            await websocket.close(code=4003)
            return
        match_mode = match.mode

    await manager.connect(match_id, websocket)
    manager.register_arena_connection(match_id, role, websocket)

    if match.status == "lobby":
        async with AsyncSessionLocal() as db:
            m_res = await db.execute(select(ArenaMatch).where(ArenaMatch.id == match_id))
            m = m_res.scalar_one_or_none()
            if m and m.status == "lobby":
                m.status = "active"
                m.started_at = datetime.utcnow()
                await db.commit()

    # Phase D: for human_defends_vs_ai matches, make sure the AI attacker
    # bot loop is running now that a participant is actually connected
    # (mirrors _stream_alerts' "start background work on a live WS event"
    # convention rather than at match-creation time — see the design note
    # above _run_arena_attacker_bot).
    _maybe_start_arena_attacker_bot(match_id, match_mode)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send_personal(websocket, build_system_event("error", {"detail": "Invalid JSON"}))
                continue

            msg_type = msg.get("type")

            if msg_type == "ping":
                await manager.send_personal(websocket, build_system_event("pong"))
                continue

            if msg_type not in ("attacker_action", "defender_action"):
                continue

            expected_role = "attacker" if msg_type == "attacker_action" else "defender"
            if role != expected_role:
                await manager.send_personal(websocket, build_system_event(
                    "error", {"detail": f"Only the {expected_role} can send {msg_type}"},
                ))
                continue

            action_type = msg.get("action_type")
            payload = msg.get("payload") or {}
            valid_types = ATTACKER_ACTION_TYPES if role == "attacker" else DEFENDER_ACTION_TYPES
            if action_type not in valid_types:
                await manager.send_personal(websocket, build_system_event(
                    "error", {"detail": f"Unknown {role} action_type '{action_type}'"},
                ))
                continue

            result = await _execute_arena_action(match_id, role, action_type, payload)
            if result is None:
                await manager.send_personal(websocket, build_system_event("error", {"detail": "Match not found or not active"}))
                continue

            await _notify_arena_action_result(match_id, role, action_type, payload, result)

    except WebSocketDisconnect:
        manager.disconnect(match_id, websocket)
        manager.unregister_arena_connection(match_id, role, websocket)

