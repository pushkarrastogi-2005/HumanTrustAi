import os
from dotenv import load_dotenv

# Load .env from backend directory
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

MONGODB_URI = os.environ["MONGODB_URI"]
DB_NAME = os.getenv("DB_NAME", "humantrust")
CHECK_INTERVAL_S = int(os.getenv("CHECK_INTERVAL_S", "10"))
SAVE_MEDIA = os.getenv("SAVE_MEDIA", "1") == "1"
EVIDENCE_ENABLED = os.getenv("EVIDENCE_ENABLED", "0") == "1"
EVIDENCE_COOLDOWN_S = int(os.getenv("EVIDENCE_COOLDOWN_S", "30"))

WEIGHTS = {
    "face": 0.30,
    "voice": 0.20,
    "liveness": 0.20,
    "behavior": 0.15,
    "session": 0.15,
}

# One module below this score forces "suspicious" regardless of the total
CRITICAL_MODULE_SCORE = 30

# ---------- Phase 3 Face & Liveness Parameters ----------
IDENTITY_ENABLED = os.getenv("IDENTITY_ENABLED", "1") == "1"
DEEPFAKE_ENABLED = os.getenv("DEEPFAKE_ENABLED", "1") == "1"
DEEPFAKE_MODEL = os.getenv("DEEPFAKE_MODEL", "prithivMLmods/Deep-Fake-Detector-v2-Model")
DEEPFAKE_EVERY_N = 3          # run the classifier on every 3rd frame per participant
DEEPFAKE_FAKE_FLOOR = float(os.getenv("DEEPFAKE_FAKE_FLOOR", "0.65"))    # Calibrated for webcam compression
AUTH_WEIGHT = float(os.getenv("AUTH_WEIGHT", "0.50"))                    # Balanced between authenticity & identity
MIN_FACE_PX = 48              # smaller faces are skipped
NO_FACE_FRAMES = 3            # consecutive no-face frames before scoring it low
LIVENESS_TTL_S = 180          # how long a liveness result counts
CHALLENGE_SECONDS = 6         # length of the recorded burst
BURST_FPS = 12                # blinks are short, so this needs to be high
