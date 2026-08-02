"""In-process WebSocket fan-out for committed Layer 4 events."""
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import WebSocket, WebSocketDisconnect

from backend.core.security import decode_token
from backend.db.session import SessionLocal
from backend.models.db.user import User
from backend.models.db.camera import Camera


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept(subprotocol="bearer")
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active:
            self.active.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        category = message.get("event_category", "SAFETY_EVENT")
        envelope = {
            "message_id": str(uuid4()),
            "event_category": category,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "data": message,
        }
        dead: list[WebSocket] = []
        for websocket in tuple(self.active):
            try:
                await websocket.send_json(envelope)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket)


alerts_manager = ConnectionManager()
manager = alerts_manager


class CameraFrameConnectionManager:
    def __init__(self) -> None:
        self.active: dict[tuple[int, bool], list[WebSocket]] = {}

    async def connect(self, camera_id: int, overlay: bool, websocket: WebSocket) -> None:
        await websocket.accept(subprotocol="bearer")
        self.active.setdefault((camera_id, overlay), []).append(websocket)

    def disconnect(self, camera_id: int, overlay: bool, websocket: WebSocket) -> None:
        key = (camera_id, overlay)
        connections = self.active.get(key)
        if not connections:
            return
        if websocket in connections:
            connections.remove(websocket)
        if not connections:
            self.active.pop(key, None)

    async def broadcast(self, camera_id: int, overlay: bool, jpeg: bytes) -> None:
        key = (camera_id, overlay)
        dead: list[WebSocket] = []
        for websocket in tuple(self.active.get(key, ())):
            try:
                await websocket.send_bytes(jpeg)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(camera_id, overlay, websocket)


camera_frames_manager = CameraFrameConnectionManager()


def authenticated_user_id(websocket: WebSocket) -> int | None:
    protocols = [
        item.strip()
        for item in websocket.headers.get("sec-websocket-protocol", "").split(",")
    ]
    token = protocols[1] if len(protocols) == 2 and protocols[0] == "bearer" else None
    payload = decode_token(token) if token else None
    if not payload or "sub" not in payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        return None
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    return user_id if user is not None else None


async def alerts_endpoint(websocket: WebSocket) -> None:
    if authenticated_user_id(websocket) is None:
        await websocket.close(code=4401, reason="Authentication required")
        return
    await alerts_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        alerts_manager.disconnect(websocket)


async def camera_frames_endpoint(
    websocket: WebSocket, camera_id: int, overlay: bool
) -> None:
    if authenticated_user_id(websocket) is None:
        await websocket.close(code=4401, reason="Authentication required")
        return
    with SessionLocal() as db:
        camera = db.query(Camera).filter(Camera.id == camera_id, Camera.deleted_at.is_(None)).first()
    if camera is None:
        await websocket.close(code=4404, reason="Camera not found")
        return
    await camera_frames_manager.connect(camera_id, overlay, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        camera_frames_manager.disconnect(camera_id, overlay, websocket)
