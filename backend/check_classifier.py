import glob
import sys
import cv2
from modules.landmarks import get_landmarks
from modules import face

if len(sys.argv) < 2:
    print("Usage: python check_classifier.py <folder_with_jpgs>")
    sys.exit(1)

ps = []
for path in glob.glob(sys.argv[1] + "/*.jpg")[:50]:
    bgr = cv2.imread(path)
    if bgr is None:
        continue
    pts = get_landmarks(bgr)
    if pts is None:
        continue
    crop, _ = face._crop(bgr, pts)
    p = face._p_fake(crop)
    if p is not None:
        ps.append(p)
        print(path, "p_fake:", round(p, 3))

print("Total valid frames:", len(ps), "Mean p_fake:", round(sum(ps) / max(len(ps), 1), 3))
