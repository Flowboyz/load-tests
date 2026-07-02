import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        # Global list of active WebSocket connections
        self.active_connections: list[WebSocket] = []
        # Mapping: session_id -> list of WebSockets subscribed to that session
        self.room_subscriptions: dict[int, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print("New WebSocket client connected.")

    def disconnect(self, websocket: WebSocket):
        # Remove from active connections
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        # Remove from any room subscriptions
        for sess_id, subs in list(self.room_subscriptions.items()):
            if websocket in subs:
                subs.remove(websocket)
                if not subs:
                    del self.room_subscriptions[sess_id]
        print("WebSocket client disconnected.")

    def join_session_room(self, session_id: int, websocket: WebSocket):
        # Ensure room list exists
        if session_id not in self.room_subscriptions:
            self.room_subscriptions[session_id] = []
        # Add connection if not already joined
        if websocket not in self.room_subscriptions[session_id]:
            self.room_subscriptions[session_id].append(websocket)
            print(f"WebSocket client subscribed to session room: {session_id}")

    async def broadcast_to_room(self, session_id: int, message: dict):
        subs = self.room_subscriptions.get(session_id, [])
        if not subs:
            return
        
        payload = json.dumps(message)
        # Send payload to all subscribed clients in parallel
        await asyncio.gather(
            *[sub.send_text(payload) for sub in subs],
            return_exceptions=True
        )

# Package level imports requirement
import asyncio
manager = ConnectionManager()

# Helper wrappers for services/metrics.py to invoke broadcasts easily
async def broadcast_raw_event(session_id: int, event: dict):
    await manager.broadcast_to_room(session_id, {
        "event_type": "session_raw_event",
        "session_id": session_id,
        "event": event
    })

async def broadcast_raw_events(session_id: int, events: list[dict]):
    await manager.broadcast_to_room(session_id, {
        "event_type": "session_raw_events",
        "session_id": session_id,
        "events": events
    })

async def broadcast_console_log(session_id: int, log: str):
    await manager.broadcast_to_room(session_id, {
        "event_type": "session_console_log",
        "session_id": session_id,
        "log": log
    })

async def broadcast_console_logs(session_id: int, logs: list[str]):
    await manager.broadcast_to_room(session_id, {
        "event_type": "session_console_logs",
        "session_id": session_id,
        "logs": logs
    })

async def broadcast_metrics(session_id: int, metrics: dict, lifecycle_summary: dict):
    await manager.broadcast_to_room(session_id, {
        "event_type": "session_metrics",
        "session_id": session_id,
        "metrics": metrics,
        "lifecycle_summary": lifecycle_summary
    })

async def broadcast_status_change(session_id: int, status: str):
    await manager.broadcast_to_room(session_id, {
        "event_type": "session_status_changed",
        "session_id": session_id,
        "status": status
    })

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Wait for messages from client (e.g. joining rooms)
            data_str = await websocket.receive_text()
            try:
                data = json.loads(data_str)
                action = data.get("action")
                if action == "join":
                    session_id = data.get("session_id")
                    if session_id is not None:
                        manager.join_session_room(int(session_id), websocket)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"Error handling websocket data: {e}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
