import random

# Debug switch for forcing anomalies while testing notifications
DEBUG = {"mode": "normal", "module": None}
RANGES = {"normal": (82, 98), "moderate": (55, 75), "suspicious": (8, 40)}


def _score(name: str) -> float:
    mode = DEBUG.get("mode", "normal")
    target_module = DEBUG.get("module")

    # If an invalid mode was set, fall back to normal
    if mode not in RANGES:
        mode = "normal"

    # If a specific module was targeted, only that module changes; others stay normal
    if target_module and target_module not in ("string", "all", "null", "none"):
        if target_module != name:
            mode = "normal"

    lo, hi = RANGES[mode]
    return round(random.uniform(lo, hi), 1)


def analyze_face(image_b64: str) -> float:
    return _score("face")


def analyze_liveness(image_b64: str) -> float:
    return _score("liveness")


def analyze_behavior(image_b64: str) -> float:
    return _score("behavior")


def analyze_voice(audio_bytes: bytes) -> float:
    return _score("voice")


def analyze_session(image_b64: str) -> float:
    return _score("session")
