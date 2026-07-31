"""In-process WebSocket fan-out for committed Layer 4 events."""
from fastapi import WebSocket, WebSocketDisconnect


class ConnectionManager:
    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active:
            self.active.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        dead: list[WebSocket] = []
        for websocket in tuple(self.active):
            try:
                await websocket.send_json(message)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket)


alerts_manager = ConnectionManager()
manager = alerts_manager


async def alerts_endpoint(websocket: WebSocket) -> None:
    await alerts_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        alerts_manager.disconnect(websocket)
