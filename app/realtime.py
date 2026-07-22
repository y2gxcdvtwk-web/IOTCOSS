from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections[session_id].add(websocket)

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        self.connections[session_id].discard(websocket)
        if not self.connections[session_id]:
            self.connections.pop(session_id, None)

    async def broadcast(self, session_id: str, message: dict) -> None:
        dead: list[WebSocket] = []
        for socket in self.connections.get(session_id, set()):
            try:
                await socket.send_json(message)
            except Exception:
                dead.append(socket)
        for socket in dead:
            self.disconnect(session_id, socket)

