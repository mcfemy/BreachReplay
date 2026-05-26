import asyncio
import json
import logging
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.session import SimulationSession, SessionParticipant, SessionDecision
from app.models.scenario import Scenario
from app.models.user import User
from app.websocket.manager import manager, build_alert_event, build_decision_gate_event, build_system_event

logger = logging.getLogger(__name__)


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

                # Autopause simulation on decision gate
                if alert.get("timestamp") in gates_by_trigger:
                    gate = gates_by_trigger[alert["timestamp"]]
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

