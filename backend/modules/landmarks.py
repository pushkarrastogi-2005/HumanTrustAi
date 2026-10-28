import base64
import threading

import cv2
import mediapipe as mp
import numpy as np

_mesh = mp.solutions.face_mesh.FaceMesh(
    static_image_mode=True,
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
)
_lock = threading.Lock()   # one FaceMesh instance is shared, so serialize calls


def decode(image_b64: str):
    arr = np.frombuffer(base64.b64decode(image_b64), np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)   # BGR, or None if corrupt


def points_from_result(res, w: int, h: int):
    """MediaPipe result -> (478, 2) array of pixel coordinates, or None."""
    if not res.multi_face_landmarks:
        return None
    lm = res.multi_face_landmarks[0].landmark
    return np.array([[p.x * w, p.y * h] for p in lm], dtype=np.float32)


def get_landmarks(bgr):
    if bgr is None:
        return None
    h, w = bgr.shape[:2]
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    with _lock:
        res = _mesh.process(rgb)
    return points_from_result(res, w, h)
