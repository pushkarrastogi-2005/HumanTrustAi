import cv2
import mediapipe as mp
import numpy as np

from modules.landmarks import decode, points_from_result

ACTIONS = {
    "blink_twice": "Blink twice",
    "turn_left": "Turn your head to YOUR left",
    "turn_right": "Turn your head to YOUR right",
    "smile": "Smile",
    "look_up": "Look up",
}

# ---------- tunable thresholds ----------
BLINK_RATIO = 0.72     # an eye counts as closed below 72% of its open-eye EAR
MAX_BLINK_FRAMES = 6   # closed for longer than this = eyes shut, not a blink
YAW_DELTA = 0.10       # change in nose position ratio that counts as a head turn
PITCH_DELTA = 0.07     # change that counts as looking up
SMILE_GAIN = 0.12      # 12% wider mouth counts as a smile
FAST_RT = 4.0          # full score if the response comes within this many seconds
YAW_LEFT_SIGN = 1      # flip to -1 if "left" and "right" come out swapped in your test

# MediaPipe FaceMesh indices: [corner, upper1, upper2, corner, lower2, lower1]
RIGHT_EYE = [33, 160, 158, 133, 153, 144]
LEFT_EYE = [362, 385, 387, 263, 373, 380]


def _ear(p, idx):
    a, b, c, d, e, f = (p[i] for i in idx)
    return (np.linalg.norm(b - f) + np.linalg.norm(c - e)) / (2.0 * np.linalg.norm(a - d) + 1e-6)


def _features(p):
    face_w = np.linalg.norm(p[454] - p[234]) + 1e-6
    ear = (_ear(p, RIGHT_EYE) + _ear(p, LEFT_EYE)) / 2.0
    yaw = (p[1][0] - p[234][0]) / (p[454][0] - p[234][0] + 1e-6)          # nose between face edges
    eye_mid_y = (p[33][1] + p[263][1]) / 2.0
    pitch = (p[1][1] - eye_mid_y) / (p[152][1] - eye_mid_y + 1e-6)        # nose between eyes and chin
    smile = np.linalg.norm(p[291] - p[61]) / face_w                       # mouth width / face width
    return ear, yaw, pitch, smile


def _fail(score, note, action, dbg=None):
    return {
        "passed": False,
        "score": score,
        "note": note,
        "response_time": None,
        "action": action,
        "debug": dbg or {},
    }


def _first_sustained(hit, k=2):
    """Index of the first run of k consecutive True values (ignores one-frame noise)."""
    for i in range(len(hit) - k + 1):
        if all(hit[i:i + k]):
            return i
    return None


def analyze(action: str, frames: list) -> dict:
    """frames: list of (timestamp_ms, base64_jpeg) in capture order."""
    feats = []
    t0 = frames[0][0] if frames else 0
    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    ) as mesh:
        for ts, img in frames:
            bgr = decode(img)
            if bgr is None:
                feats.append(None)
                continue
            h, w = bgr.shape[:2]
            res = mesh.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            pts = points_from_result(res, w, h)
            feats.append(None if pts is None else ((ts - t0) / 1000.0, *_features(pts)))

    valid = [f for f in feats if f is not None]
    if not frames or len(valid) < 0.6 * len(frames):
        return _fail(10.0, "Face not visible during the liveness challenge", action)

    T, EAR, YAW, PITCH, SMILE = np.array(valid, dtype=np.float32).T
    duration = float(T[-1])
    k = min(3, len(T))
    base_yaw, base_pitch, base_smile = (float(np.median(x[:k])) for x in (YAW, PITCH, SMILE))

    rt, dbg = None, {}
    if action == "blink_twice":
        open_ear = float(np.percentile(EAR, 80))
        closed = EAR < BLINK_RATIO * open_ear
        blinks, i = [], 0
        while i < len(closed):
            if closed[i]:
                j = i
                while j < len(closed) and closed[j]:
                    j += 1
                if j - i <= MAX_BLINK_FRAMES:
                    blinks.append(float(T[i]))
                i = j
            else:
                i += 1
        dbg = {
            "open_ear": round(open_ear, 3),
            "min_ear": round(float(EAR.min()), 3),
            "blinks": len(blinks),
        }
        if open_ear > 0.15 and len(blinks) >= 2:
            rt = blinks[1]                       # time of the second blink
    else:
        if action == "turn_left":
            sig, thr = YAW_LEFT_SIGN * (YAW - base_yaw), YAW_DELTA
        elif action == "turn_right":
            sig, thr = -YAW_LEFT_SIGN * (YAW - base_yaw), YAW_DELTA
        elif action == "smile":
            sig, thr = (SMILE - base_smile) / (base_smile + 1e-6), SMILE_GAIN
        else:                                    # look_up
            sig, thr = base_pitch - PITCH, PITCH_DELTA
        idx = _first_sustained(sig > thr)
        dbg = {"best_signal": round(float(sig.max()), 3), "threshold": thr}
        if idx is not None:
            rt = float(T[idx])

    if rt is None:
        return _fail(15.0, "Liveness challenge not completed", action, dbg)

    if rt <= FAST_RT:
        score = 100.0
    else:
        score = max(70.0, 100.0 - 30.0 * (rt - FAST_RT) / max(duration - FAST_RT, 0.5))
    return {
        "passed": True,
        "score": round(score, 1),
        "note": None,
        "response_time": round(rt, 2),
        "action": action,
        "debug": dbg,
    }
