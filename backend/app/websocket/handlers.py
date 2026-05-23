import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.session import SimulationSession
from app.models.scenario import Scenario
from app.websocket.manager import manager, build_alert_event, build_decision_gate_event, build_system_event


async def simulation_ws_handler(websocket: WebSocket, session_id: str, user_id: str):
    await manager.connect(session_id, websocket)
    await manager.broadcast(session_id, build_system_event("participant_joined", {"user_id": user_id, "count": manager.session_size(session_id)}))
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
                    "text": msg.get("text", "")[:2000],
                })

            elif msg_type == "ping":
                await manager.send_personal(websocket, build_system_event("pong"))

            elif msg_type == "stream_alerts":
                asyncio.create_task(_stream_alerts(session_id, user_id))

    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)
        await manager.broadcast(session_id, build_system_event("participant_left", {"user_id": user_id, "count": manager.session_size(session_id)}))


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
        decision_tree = {g["id"]: g for g in (scenario.decision_tree or [])}
        gates_by_trigger = {}
        for gate in (scenario.decision_tree or []):
            gates_by_trigger.setdefault(gate["trigger_timestamp"], gate)

        total = len(alerts)
        speed = session.speed_multiplier or 1.0

        for i, alert in enumerate(alerts):
            await manager.broadcast(session_id, build_alert_event(alert, i, total))

            if alert.get("timestamp") in gates_by_trigger:
                gate = gates_by_trigger[alert["timestamp"]]
                await manager.broadcast(session_id, build_decision_gate_event(gate))
                await asyncio.sleep(0)

            interval = 3.0 / speed
            await asyncio.sleep(interval)

        await manager.broadcast(session_id, build_system_event("simulation_complete"))
