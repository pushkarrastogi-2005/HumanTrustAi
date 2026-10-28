import base64
import sys
import time
import cv2
from modules import liveness

if len(sys.argv) < 2:
    print(f"Usage: python test_liveness.py <action>\nAvailable actions: {list(liveness.ACTIONS.keys())}")
    sys.exit(1)

action = sys.argv[1]
if action not in liveness.ACTIONS:
    print(f"Unknown action '{action}'. Choose from: {list(liveness.ACTIONS.keys())}")
    sys.exit(1)

cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("Error: Could not open webcam (index 0).")
    sys.exit(1)

print("Get ready...")
time.sleep(2)
print("GO:", liveness.ACTIONS[action])
frames, t_end = [], time.time() + 6
while time.time() < t_end:
    ok, frame = cap.read()
    if not ok:
        break
    frame = cv2.resize(frame, (480, int(frame.shape[0] * 480 / frame.shape[1])))
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
    frames.append((int(time.time() * 1000), base64.b64encode(buf).decode()))
    time.sleep(1 / 12)
cap.release()
print("\n--- Result ---")
print(liveness.analyze(action, frames))
