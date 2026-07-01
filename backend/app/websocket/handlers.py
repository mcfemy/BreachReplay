import asyncio
import json
import logging
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select, text
from app.db.session import AsyncSessionLocal
from app.models.session import SimulationSession, SessionParticipant, SessionDecision
from app.models.scenario import Scenario
from app.models.user import User
from app.websocket.manager import (
    manager,
    build_alert_event,
    build_decision_gate_event,
    build_system_event,
    build_investigation_result_event,
)
from app.pipeline.claude_client import generate_decision_commentary
from app.services.siem_service import send_alert_to_siem, send_decision_to_siem

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

