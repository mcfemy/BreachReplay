import asyncio
import json
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.streaming_sessions: Set[str] = set()
        # Multiplayer presence: session_id -> user_id -> {"name": str, "role": str, "websocket": WebSocket, "online": bool}
        self.presence: Dict[str, Dict[str, dict]] = {}
        # Active voting consensus: session_id -> user_id -> chosen_index (int)
        self.votes: Dict[str, Dict[str, int]] = {}
        # Simulation statuses: session_id -> str ("waiting", "active", "paused", "completed")
        self.statuses: Dict[str, str] = {}
        # Dynamic alert inject queues: session_id -> list[dict]
        self.inject_queues: Dict[str, list] = {}
        # Pause synchronization events: session_id -> asyncio.Event
        self.pause_events: Dict[str, asyncio.Event] = {}
        # Serialises concurrent presence mutations to prevent race conditions on disconnect/reconnect
        self._presence_lock: asyncio.Lock = asyncio.Lock()

    def get_pause_event(self, session_id: str) -> asyncio.Event:
        if session_id not in self.pause_events:
            event = asyncio.Event()
            event.set()  # Default is running (set = running)
            self.pause_events[session_id] = event
        return self.pause_events[session_id]

    def pause_session(self, session_id: str):
        self.get_pause_event(session_id).clear()
        self.statuses[session_id] = "paused"

    def resume_session(self, session_id: str):
        self.get_pause_event(session_id).set()
        self.statuses[session_id] = "active"

    def is_paused(self, session_id: str) -> bool:
        return not self.get_pause_event(session_id).is_set()

    def queue_inject_alert(self, session_id: str, alert: dict):
        if session_id not in self.inject_queues:
            self.inject_queues[session_id] = []
        self.inject_queues[session_id].append(alert)

    def pop_injected_alerts(self, session_id: str) -> list:
        alerts = self.inject_queues.get(session_id, [])
        self.inject_queues[session_id] = []
        return alerts

    async def add_user_presence(self, session_id: str, user_id: str, name: str, role: str, websocket: WebSocket):
        async with self._presence_lock:
            if session_id not in self.presence:
                self.presence[session_id] = {}
            self.presence[session_id][user_id] = {
                "name": name,
                "role": role,
                "websocket": websocket,
                "online": True
            }
        await self.broadcast_lobby_state(session_id)

    async def remove_user_presence(self, session_id: str, user_id: str):
        async with self._presence_lock:
            if session_id in self.presence and user_id in self.presence[session_id]:
                self.presence[session_id][user_id]["online"] = False
        await self.broadcast_lobby_state(session_id)

    def record_vote(self, session_id: str, user_id: str, option_index: int):
        if session_id not in self.votes:
            self.votes[session_id] = {}
        self.votes[session_id][user_id] = option_index

    def clear_votes(self, session_id: str):
        if session_id in self.votes:
            self.votes[session_id] = {}

    async def broadcast_lobby_state(self, session_id: str):
        if session_id not in self.presence:
            return
        participants = [
            {
                "user_id": uid,
                "name": u["name"],
                "role": u["role"],
                "online": u["online"]
            }
            for uid, u in self.presence[session_id].items()
        ]
        await self.broadcast(session_id, {
            "type": "presence_update",
            "participants": participants,
            "count": self.session_size(session_id)
        })

    async def broadcast_vote_state(self, session_id: str):
        votes_map = self.votes.get(session_id, {})
        vote_data = [
            {"user_id": uid, "chosen_index": idx}
            for uid, idx in votes_map.items()
        ]
        await self.broadcast(session_id, {
            "type": "vote_update",
            "votes": vote_data
        })

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


def build_investigation_result_event(field: str, value: str, matches: list) -> dict:
    return {
        "type": "investigation_result",
        "query": {"field": field, "value": value},
        "matches": matches,
        "server_time": datetime.utcnow().isoformat(),
    }
