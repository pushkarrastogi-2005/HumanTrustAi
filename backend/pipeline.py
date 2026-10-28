import asyncio
import time

import state
import scoring
from config import CHECK_INTERVAL_S, EVIDENCE_ENABLED, EVIDENCE_COOLDOWN_S
from db import scores, alerts
from evidence import upload_frame
from ws_manager import manager


async def attach_evidence(session_id, pid, alert_id, image_b64, ts):
    try:
        ev = await upload_frame(image_b64, session_id, pid, ts)
    except Exception as e:
        print("evidence upload failed:", e)   # never break the alert flow
        return
    await alerts.update_one(
        {"_id": alert_id},
        {"$set": {"evidence_url": ev["url"], "evidence_id": ev["public_id"]}},
    )
    await manager.send(session_id, {
        "type": "evidence",
        "participant_id": pid,
        "ts": ts,
        "url": ev["url"],
    })


async def maybe_check(session_id: str, pid: str, force: bool = False):
    st = state.participant(session_id, pid)
    now = time.time()
    if not force and now - st["last_check"] < CHECK_INTERVAL_S:
        return

    result = scoring.compute(state.averaged(session_id, pid), state.notes(session_id, pid))
    if result is None:
        return

    st["last_check"] = now
    ts = int(now * 1000)
    p_name = st.get("name")

    await scores.insert_one({
        "session_id": session_id,
        "participant_id": pid,
        "name": p_name,
        "ts": ts,
        "modules": result["modules"],
        "total": result["total"],
        "status": result["status"],
        "reason": result["reason"],
    })

    alert_id = None
    if result["status"] != "verified":
        ins = await alerts.insert_one({
            "session_id": session_id,
            "participant_id": pid,
            "name": p_name,
            "ts": ts,
            "status": result["status"],
            "reason": result["reason"],
            "weakest": result["weakest"],
            "total": result["total"],
            "evidence_url": None,
        })
        alert_id = ins.inserted_id

    # Sent for EVERY check, normal or anomaly
    await manager.send(session_id, {
        "type": "result",
        "session_id": session_id,
        "participant_id": pid,
        "name": p_name,
        "ts": ts,
        "total": result["total"],
        "status": result["status"],
        "reason": result["reason"],
        "modules": result["modules"],
    })

    # Evidence: suspicious only, with a cooldown, after the notification
    if (
        EVIDENCE_ENABLED
        and result["status"] == "suspicious"
        and st["last_frame"]
        and now - st["last_evidence"] >= EVIDENCE_COOLDOWN_S
    ):
        st["last_evidence"] = now
        asyncio.create_task(
            attach_evidence(session_id, pid, alert_id, st["last_frame"], ts)
        )
