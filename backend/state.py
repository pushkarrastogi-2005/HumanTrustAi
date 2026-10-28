import time
from collections import deque

from config import WEIGHTS, LIVENESS_TTL_S

WINDOW = 5
_participants = {}
_voice = {}


def participant(session_id: str, pid: str) -> dict:
    key = (session_id, pid)
    if key not in _participants:
        _participants[key] = {
            "name": None,
            "scores": {m: deque(maxlen=WINDOW) for m in WEIGHTS},
            "notes": {},
            "last_check": 0.0,
            "last_frame": None,
            "last_evidence": 0.0,
            "frame_count": 0,
            "no_face": 0,
            "ref_embs": [],
            "ref_emb": None,
            "last_auth": None,
            "liveness": None,      # (score, timestamp)
            "challenge": None,     # pending challenge
        }
    return _participants[key]


def add(session_id: str, pid: str, module: str, value: float):
    participant(session_id, pid)["scores"][module].append(value)


def set_only(session_id: str, pid: str, module: str, value: float):
    """Replace the whole rolling window, so a sudden failure shows up immediately."""
    dq = participant(session_id, pid)["scores"][module]
    dq.clear()
    dq.append(value)


def note(session_id: str, pid: str, module: str, text):
    notes = participant(session_id, pid)["notes"]
    if text:
        notes[module] = text
    else:
        notes.pop(module, None)


def notes(session_id: str, pid: str) -> dict:
    return dict(participant(session_id, pid)["notes"])


def set_liveness(session_id: str, pid: str, value: float, text=None):
    participant(session_id, pid)["liveness"] = (value, time.time())
    note(session_id, pid, "liveness", text)


def set_voice(session_id: str, value: float):
    _voice.setdefault(session_id, deque(maxlen=WINDOW)).append(value)


def averaged(session_id: str, pid: str) -> dict:
    st = participant(session_id, pid)
    out = {}
    for module, dq in st["scores"].items():
        if module == "liveness":
            lv = st["liveness"]
            out[module] = lv[0] if lv and time.time() - lv[1] <= LIVENESS_TTL_S else None
            continue
        if module == "voice":
            dq = _voice.get(session_id, [])
        out[module] = round(sum(dq) / len(dq), 1) if dq else None
    return out


def clear_session(session_id: str):
    for key in [k for k in _participants if k[0] == session_id]:
        del _participants[key]
    _voice.pop(session_id, None)
