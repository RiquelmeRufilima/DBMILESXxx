from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from fastapi import WebSocket


class RealtimeConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[int, dict[WebSocket, int]] = defaultdict(dict)

    async def connect(self, company_id: int, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections[company_id][websocket] = user_id

    def disconnect(self, company_id: int, websocket: WebSocket) -> None:
        self.connections[company_id].pop(websocket, None)
        if not self.connections[company_id]:
            self.connections.pop(company_id, None)

    async def disconnect_user(self, user_id: int, code: int = 4403) -> None:
        targets: list[tuple[int, WebSocket]] = []
        for company_id, connections in list(self.connections.items()):
            for websocket, connected_user_id in list(connections.items()):
                if connected_user_id == user_id:
                    targets.append((company_id, websocket))
        for company_id, websocket in targets:
            self.disconnect(company_id, websocket)
            try:
                await websocket.close(code=code)
            except Exception:
                pass

    async def broadcast(self, company_id: int, payload: dict) -> None:
        dead: list[WebSocket] = []
        for connection in list(self.connections.get(company_id, {})):
            try:
                await connection.send_json(payload)
            except Exception:
                dead.append(connection)
        for connection in dead:
            self.disconnect(company_id, connection)


manager = RealtimeConnectionManager()


def avatar_url(user) -> str | None:
    profile = getattr(user, "profile", None)
    path = getattr(profile, "avatar_path", None) if profile else None
    if not path:
        return None
    updated = getattr(profile, "updated_at", None)
    version = int(updated.timestamp()) if isinstance(updated, datetime) else 0
    return f"/{path}?v={version}"


def profile_event(user) -> dict:
    profile = getattr(user, "profile", None)
    return {
        "type": "profile_updated",
        "user_id": user.id,
        "user_name": user.name,
        "role": user.role,
        "job_title": getattr(profile, "job_title", None) if profile else None,
        "avatar_url": avatar_url(user),
        "updated_at": (
            profile.updated_at.isoformat()
            if profile and getattr(profile, "updated_at", None)
            else datetime.utcnow().isoformat()
        ),
    }
