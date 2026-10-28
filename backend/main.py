import base64
import os
import random
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import state
from config import (
    SAVE_MEDIA,
    NO_FACE_FRAMES,
    CHALLENGE_SECONDS,
    BURST_FPS,
)
from db import sessions, scores, alerts
from modules import placeholders as mod
from modules import face as face_module, liveness
from pipeline import maybe_check
from ws_manager import manager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRAMES_DIR = os.path.join(BASE_DIR, "received", "frames")
AUDIO_DIR = os.path.join(BASE_DIR, "received", "audio")

os.makedirs(FRAMES_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure indexes on session_id and ts for fast queries
    await scores.create_index([("session_id", 1), ("ts", 1)])
    await alerts.create_index([("session_id", 1), ("ts", 1)])
    # Warm up models at startup so the first frame isn't delayed
    await run_in_threadpool(face_module.warm_up)
    yield


app = FastAPI(title="HumanTrust AI - Phase 3 Backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Frame(BaseModel):
    session_id: str
    participant_id: str
    ts: int
    image: str  # base64 JPEG
    name: Optional[str] = None


class SessionRef(BaseModel):
    session_id: str


class ChallengeReq(BaseModel):
    session_id: str
    participant_id: str
    participant_name: Optional[str] = None


class BurstFrame(BaseModel):
    ts: int
    image: str


class Burst(BaseModel):
    session_id: str
    participant_id: str
    challenge_id: str
    frames: list[BurstFrame]


class DebugMode(BaseModel):
    mode: str = Field(
        default="suspicious",
        description="Mode: 'suspicious', 'moderate', or 'normal'",
    )
    module: Optional[str] = Field(
        default=None,
        description="Optional: 'face', 'voice', 'liveness', 'behavior', 'session', or null for all modules",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "mode": "suspicious",
                "module": None,
            }
        }
    }


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "HumanTrust AI - Phase 3 Backend",
        "phase": 3,
    }


@app.post("/session/start")
async def start():
    sid = uuid.uuid4().hex[:12]
    await sessions.insert_one({
        "_id": sid,
        "started_at": int(time.time() * 1000),
        "ended_at": None,
        "status": "active",
    })
    return {"session_id": sid}


@app.post("/session/end")
async def end(body: SessionRef):
    sid = body.session_id
    agg = await scores.aggregate([
        {"$match": {"session_id": sid}},
        {
            "$group": {
                "_id": None,
                "avg": {"$avg": "$total"},
                "min": {"$min": "$total"},
                "checks": {"$sum": 1},
            }
        },
    ]).to_list(1)
    summary = agg[0] if agg else {"avg": None, "min": None, "checks": 0}
    summary.pop("_id", None)
    summary["alerts"] = await alerts.count_documents({"session_id": sid})

    await sessions.update_one(
        {"_id": sid},
        {
            "$set": {
                "ended_at": int(time.time() * 1000),
                "status": "ended",
                "summary": summary,
            }
        },
    )
    state.clear_session(sid)
    return {"ok": True, "summary": summary}


@app.post("/frame")
async def frame(f: Frame):
    t_start = time.perf_counter()
    if SAVE_MEDIA:
        path = os.path.join(FRAMES_DIR, f"{f.session_id}_{f.participant_id}_{f.ts}.jpg")
        with open(path, "wb") as out:
            out.write(base64.b64decode(f.image))

    sid, pid = f.session_id, f.participant_id
    st = state.participant(sid, pid)
    st["last_frame"] = f.image
    if f.name:
        st["name"] = f.name

    # Real face analysis (authenticity + identity)
    res = await run_in_threadpool(face_module.analyze, f.image, st)
    if res["status"] == "no_face":
        st["no_face"] += 1
        if st["no_face"] >= NO_FACE_FRAMES:
            state.set_only(sid, pid, "face", 15.0)
            state.note(sid, pid, "face", "No face detected in the video")
    else:
        st["no_face"] = 0
        if res["status"] == "ok":
            state.add(sid, pid, "face", res["score"])
            state.note(sid, pid, "face", res["note"])  # None clears previous note

    # Voice, Behavior & Session remain placeholders until Phases 4-5
    state.add(sid, pid, "behavior", mod.analyze_behavior(f.image))
    state.add(sid, pid, "session", mod.analyze_session(f.image))

    await maybe_check(sid, pid)
    dt = time.perf_counter() - t_start
    if dt > 1.0:
        print(f"[frame] {pid} took {dt:.2f}s (backend is falling behind)")
    return {"ok": True, "face": res}


@app.post("/audio")
async def audio(
    session_id: str = Form(...),
    ts: int = Form(...),
    file: UploadFile = File(...),
):
    data = await file.read()
    if SAVE_MEDIA:
        path = os.path.join(AUDIO_DIR, f"{session_id}_{ts}.webm")
        with open(path, "wb") as out:
            out.write(data)
    state.set_voice(session_id, mod.analyze_voice(data))
    return {"ok": True}


# ---------- Phase 3 Interactive Liveness Endpoints ----------
@app.post("/liveness/challenge")
async def new_challenge(req: ChallengeReq):
    action = random.choice(list(liveness.ACTIONS))
    cid = uuid.uuid4().hex[:8]
    st = state.participant(req.session_id, req.participant_id)
    if req.participant_name:
        st["name"] = req.participant_name
    st["challenge"] = {"id": cid, "action": action, "issued": time.time()}
    return {
        "challenge_id": cid,
        "action": action,
        "instruction": liveness.ACTIONS[action],
        "duration_s": CHALLENGE_SECONDS,
        "fps": BURST_FPS,
    }


@app.post("/liveness/burst")
async def liveness_burst(b: Burst):
    sid, pid = b.session_id, b.participant_id
    st = state.participant(sid, pid)
    ch = st.get("challenge")
    if not ch or ch["id"] != b.challenge_id or time.time() - ch["issued"] > CHALLENGE_SECONDS + 30:
        return {"ok": False, "error": "unknown or expired challenge"}
    st["challenge"] = None  # Single-use challenge

    frames = [(fr.ts, fr.image) for fr in b.frames]
    res = await run_in_threadpool(liveness.analyze, ch["action"], frames)
    state.set_liveness(sid, pid, res["score"], res["note"])
    await maybe_check(sid, pid, force=True)  # Notify immediately
    return {"ok": True, **res}


@app.websocket("/ws/{session_id}")
async def ws_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(session_id, websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)


# ---- read endpoints (dashboard uses these in Phase 5) ----
@app.get("/sessions")
async def list_sessions():
    return await sessions.find().sort("started_at", -1).to_list(100)


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    s = await sessions.find_one({"_id": session_id})
    sc = await scores.find({"session_id": session_id}, {"_id": 0}).sort("ts", 1).to_list(5000)
    al = await alerts.find({"session_id": session_id}, {"_id": 0}).sort("ts", 1).to_list(1000)
    return {"session": s, "scores": sc, "alerts": al}


# ---- testing helper: force anomalies to check notifications ----
@app.post("/debug/mode")
async def debug_mode(d: DebugMode):
    mode = str(d.mode).lower().strip()
    if mode not in mod.RANGES:
        if "susp" in mode:
            mode = "suspicious"
        elif "mod" in mode:
            mode = "moderate"
        else:
            mode = "suspicious"

    valid_modules = {"face", "voice", "liveness", "behavior", "session"}
    raw_mod = str(d.module).lower().strip() if d.module is not None else None
    if raw_mod in valid_modules:
        target_mod = raw_mod
    else:
        target_mod = None

    mod.DEBUG["mode"] = mode
    mod.DEBUG["module"] = target_mod
    print(f"[Debug Mode Updated] mode: {mode}, module: {target_mod}")
    return {
        "ok": True,
        "mode": mode,
        "module": target_mod or "all modules",
        "message": f"Simulation set to '{mode}' for " + (f"module '{target_mod}'" if target_mod else "all modules"),
    }
