from config import WEIGHTS, CRITICAL_MODULE_SCORE

REASONS = {
    "face": "Face looks manipulated or inconsistent",
    "voice": "Voice may be synthetic or cloned",
    "liveness": "Liveness check failed or response was too slow",
    "behavior": "Unnatural gaze, blinking or lip-sync",
    "session": "Possible replayed or looped video",
}


def classify(total: float) -> str:
    if total >= 80:
        return "verified"
    if total >= 60:
        return "moderate"
    return "suspicious"


def compute(modules: dict, notes: dict = None):
    """modules: {"face": 91.0, "voice": None, ...}. None means no data yet."""
    present = {k: v for k, v in modules.items() if v is not None}
    if not present:
        return None

    # Re-normalise the weights over the modules that have data
    wsum = sum(WEIGHTS[k] for k in present)
    total = round(sum(WEIGHTS[k] * v for k, v in present.items()) / wsum, 1)

    status = classify(total)
    weakest = min(present, key=present.get)
    if present[weakest] < CRITICAL_MODULE_SCORE:
        status = "suspicious"

    return {
        "total": total,
        "status": status,
        "reason": ((notes or {}).get(weakest) or REASONS[weakest]) if status != "verified" else None,
        "weakest": weakest,
        "modules": modules,
    }
