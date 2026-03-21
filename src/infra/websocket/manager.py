from fastapi import WebSocket

class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[Websocket]] = {}

    async def connect(self, socket: WebSocket, user_id: str):
        await socket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(socket)

    async def disconnect(self, socket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(socket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def broadcast_to_user(self, socket: WebSocket, user_id: str, data):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                await connection.send_json(data) 