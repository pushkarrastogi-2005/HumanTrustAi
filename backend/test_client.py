import asyncio
import json
import httpx
import websockets

API = "http://localhost:8000"
# Tiny valid 1x1 JPEG so Cloudinary test also succeeds if triggered
VALID_JPEG = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="


async def main():
    async with httpx.AsyncClient(timeout=10.0) as c:
        sid = (await c.post(f"{API}/session/start")).json()["session_id"]
        print("Session started:", sid)

        async with websockets.connect(f"ws://localhost:8000/ws/{sid}") as ws:
            async def sender():
                for i in range(10):  # send 10 frames for testing
                    await c.post(f"{API}/frame", json={
                        "session_id": sid,
                        "participant_id": "p1",
                        "ts": i,
                        "image": VALID_JPEG
                    })
                    await asyncio.sleep(1.5)

            task = asyncio.create_task(sender())
            while not task.done():
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    d = json.loads(msg)
                    print(f"WS Event -> Type: {d.get('type')}, Status: {d.get('status')}, Total: {d.get('total')}, Reason: {d.get('reason')}")
                except asyncio.TimeoutError:
                    pass

        res = (await c.post(f"{API}/session/end", json={"session_id": sid})).json()
        print("Session ended. Summary:", res)

if __name__ == "__main__":
    asyncio.run(main())
