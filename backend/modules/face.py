import cv2
import numpy as np

from config import (
    AUTH_WEIGHT,
    DEEPFAKE_ENABLED,
    DEEPFAKE_EVERY_N,
    DEEPFAKE_FAKE_FLOOR,
    DEEPFAKE_MODEL,
    IDENTITY_ENABLED,
    MIN_FACE_PX,
)
from modules.landmarks import decode, get_landmarks

_classifier = None
_classifier_failed = False
_deepface = None
_identity_failed = False


def _crop(bgr, pts, margin=0.25):
    h, w = bgr.shape[:2]
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    bw, bh = x1 - x0, y1 - y0
    x0, x1 = int(max(0, x0 - margin * bw)), int(min(w, x1 + margin * bw))
    y0, y1 = int(max(0, y0 - margin * bh)), int(min(h, y1 + margin * bh))
    return bgr[y0:y1, x0:x1], (bw, bh)


# ---------- authenticity (deepfake classifier) ----------
def _get_classifier():
    global _classifier, _classifier_failed
    if _classifier is None and not _classifier_failed:
        try:
            from transformers import pipeline
            _classifier = pipeline("image-classification", model=DEEPFAKE_MODEL, device=-1)
        except Exception as e:
            print("[face] deepfake model unavailable:", e)
            _classifier_failed = True
    return _classifier


def _p_fake(face_bgr):
    """Raw probability (0-1) that the face is fake, or None if the model is unavailable."""
    clf = _get_classifier()
    if clf is None:
        return None
    from PIL import Image
    img = Image.fromarray(cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB))
    p = 0.0
    for o in clf(img, top_k=2):
        if "fake" in o["label"].lower():   # matches the "Deepfake" label
            p = float(o["score"])
    return p


def _authenticity(face_bgr):
    p = _p_fake(face_bgr)
    if p is None:
        return None
    if p <= DEEPFAKE_FAKE_FLOOR:
        return 100.0
    return max(0.0, 100.0 * (1.0 - p) / (1.0 - DEEPFAKE_FAKE_FLOOR))


# ---------- identity (same person as at the start?) ----------
def _embed(face_bgr):
    global _deepface
    if _deepface is None:
        from deepface import DeepFace
        _deepface = DeepFace
    rep = _deepface.represent(
        img_path=face_bgr,
        model_name="SFace",
        detector_backend="skip",
        enforce_detection=False,
    )
    v = np.asarray(rep[0]["embedding"], dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def _identity_score(st, emb):
    """Enrol the first 3 faces as the reference, then compare every new face to it."""
    refs = st["ref_embs"]
    if len(refs) < 3:
        refs.append(emb)
        if len(refs) == 3:
            m = np.mean(refs, axis=0)
            st["ref_emb"] = m / (np.linalg.norm(m) + 1e-9)
        return None  # still enrolling

    dist = 1.0 - float(np.dot(st["ref_emb"], emb))  # cosine distance

    # Smoothly adapt reference embedding to accommodate natural head tilt, angle, and lighting
    if dist < 0.45:
        st["ref_emb"] = 0.95 * st["ref_emb"] + 0.05 * emb
        st["ref_emb"] = st["ref_emb"] / (np.linalg.norm(st["ref_emb"]) + 1e-9)

    # 0.45 or less -> 100 (same person with natural pose/angle variance)
    # 0.72 or more -> 0 (different person / swapped face)
    if dist <= 0.45:
        return 100.0
    if dist >= 0.72:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (0.72 - dist) / 0.27))


# ---------- main entry ----------
def analyze(image_b64: str, st: dict) -> dict:
    """Returns {"status": "ok" | "no_face" | "skip", "score", "note", "parts"}."""
    global _identity_failed
    bgr = decode(image_b64)
    pts = get_landmarks(bgr)
    if pts is None:
        return {"status": "no_face"}

    face, (bw, bh) = _crop(bgr, pts)
    if face.size == 0 or min(bw, bh) < MIN_FACE_PX:
        return {"status": "skip", "note": "Face too small to analyze"}

    st["frame_count"] += 1
    ident = None
    if IDENTITY_ENABLED and not _identity_failed:
        try:
            ident = _identity_score(st, _embed(face))
        except Exception as e:
            print("[face] identity check disabled:", e)
            _identity_failed = True

    auth = None
    if DEEPFAKE_ENABLED:
        if st["last_auth"] is None or (st["frame_count"] - 1) % DEEPFAKE_EVERY_N == 0:
            try:
                st["last_auth"] = _authenticity(face)
            except Exception as e:
                print("[face] classifier error:", e)
        auth = st["last_auth"]

    parts = {
        "identity": None if ident is None else round(ident, 1),
        "authenticity": None if auth is None else round(auth, 1),
    }
    if ident is None and auth is None:
        return {"status": "skip", "parts": parts}

    if ident is not None and auth is not None:
        score = AUTH_WEIGHT * auth + (1 - AUTH_WEIGHT) * ident
    else:
        score = ident if ident is not None else auth

    # Only set alarming notes if there is genuine strong deviation,
    # avoiding false alarms from normal head tilting, lighting changes, or compression.
    note = None
    if ident is not None and ident < 50.0:
        note = "Face identity changed during the call"
    elif auth is not None and auth < 50.0:
        note = "Face looks manipulated or synthetic"

    return {"status": "ok", "score": round(score, 1), "note": note, "parts": parts}


def warm_up():
    """Load the models at startup so the first real frame isn't slow."""
    if DEEPFAKE_ENABLED:
        _get_classifier()
    if IDENTITY_ENABLED:
        try:
            _embed(np.zeros((112, 112, 3), np.uint8))
        except Exception as e:
            print("[face] identity warm-up failed:", e)
