import base64
import sys
import state
from modules import face

if len(sys.argv) < 2:
    print("Usage: python test_face.py <path_to_image.jpg>")
    sys.exit(1)

img = base64.b64encode(open(sys.argv[1], "rb").read()).decode()
st = state.participant("t", "p1")
print(f"Testing face analysis on {sys.argv[1]} across 6 frames:")
for i in range(6):
    res = face.analyze(img, st)
    print(f"Frame {i+1}: {res}")
