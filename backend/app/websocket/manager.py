import asyncio
import json
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.streaming_sessions: Set[str] = set()

    def start_streaming(self, session_id: str) -> bool:
        """Mark a session as streaming. Returns False if already streaming."""
        if session_id in self.streaming_sessions:
            return False
        self.streaming_sessions.add(session_id)
        return True

    def stop_streaming(self, session_id: str):
        """Remove a session from streaming state."""
        self.streaming_sessions.discard(session_id)

    async def connect(self, session_id: str, websocket: WebSocket):
        # Caller (websocket_session in main.py) already called websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()
        self.active_connections[session_id].add(websocket)

    def disconnect(self, session_id: str, websocket: WebSocket):
        if session_id in self.active_connections:
            self.active_connections[session_id].discard(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

    async def broadcast(self, session_id: str, message: dict):
        if session_id not in self.active_connections:
            return
        dead = set()
        for ws in self.active_connections[session_id]:
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.active_connections[session_id].discard(ws)

    async def send_personal(self, websocket: WebSocket, message: dict):
        await websocket.send_json(message)

    def session_size(self, session_id: str) -> int:
        return len(self.active_connections.get(session_id, set()))


manager = ConnectionManager()


def build_alert_event(alert: dict, index: int, total: int) -> dict:
    return {
        "type": "alert",
        "index": index,
        "total": total,
        "payload": alert,
        "server_time": datetime.utcnow().isoformat(),
    }


def build_decision_gate_event(gate: dict) -> dict:
    return {
        "type": "decision_gate",
        "gate_id": gate["id"],
        "context_summary": gate["context_summary"],
        "options": [{"index": i, "text": opt["text"]} for i, opt in enumerate(gate["options"])],
        "server_time": datetime.utcnow().isoformat(),
    }


def build_system_event(event_type: str, data: dict = None) -> dict:
    return {
        "type": event_type,
        "data": data or {},
        "server_time": datetime.utcnow().isoformat(),
    }
