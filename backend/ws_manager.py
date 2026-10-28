from collections import defaultdict
from fastapi import WebSocket


class Manager:
    def __init__(self):
        self.conns = defaultdict(set)

    async def connect(self, session_id: str, ws: WebSocket):
        await ws.accept()
        self.conns[session_id].add(ws)

    def disconnect(self, session_id: str, ws: WebSocket):
        self.conns[session_id].discard(ws)

    async def send(self, session_id: str, data: dict):
        dead = []
        for ws in list(self.conns[session_id]):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(session_id, ws)


manager = Manager()
