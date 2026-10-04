#!/usr/bin/env python3
"""
Screentest capture: watch one viewer through a webcam while they watch a film,
and write once-per-second numbers the Screentest dashboard can load.

Nothing but numbers is saved. No frames, no video, no face images.

Setup (once):
    pip install mediapipe opencv-python numpy

Run (one viewer per run, press Enter the moment the film starts):
    python capture.py --viewer v01 --film "Landlord, cut 3"

Stop with Ctrl+C when the film ends, or pass --minutes 94 to stop on its own.
The output is sessions/<film>__<viewer>.json. Load all of a screening's files
into the dashboard together.

Get consent first. Tell viewers the camera is measuring where they look and
how they react, that no video is kept, and let them opt out.
"""
import argparse, json, math, os, re, sys, time, urllib.request

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")
YAW_LIMIT, PITCH_LIMIT = 25.0, 20.0     # degrees away from this viewer's usual head position
LOOKDOWN_LIMIT = 0.35                   # eyes dropped well below their usual line (phone check)
NOSE, LEFT_EDGE, RIGHT_EDGE = 1, 234, 454


def get_model(path):
    if os.path.exists(path):
        return path
    print(f"Downloading the face model to {path} (about 4 MB, one time)...")
    urllib.request.urlretrieve(MODEL_URL, path)
    return path


def head_angles(matrix):
    """Yaw and pitch in degrees from MediaPipe's 4x4 face transform."""
    r = np.asarray(matrix)[:3, :3]
    yaw = math.degrees(math.atan2(-r[2, 0], math.hypot(r[0, 0], r[1, 0])))
    pitch = math.degrees(math.atan2(r[2, 1], r[2, 2]))
    return yaw, pitch


class SecondBucket:
    """Collects frame readings for one second of film time."""
    def __init__(self):
        self.frames = 0; self.found = 0
        self.yaw = []; self.pitch = []; self.lookdown = []
        self.smile = 0.0; self.motion = 0.0; self.blinks = 0


def summarise(buckets, n_seconds):
    face = [0] * n_seconds; motion = [0.0] * n_seconds; smile_raw = [0.0] * n_seconds
    blink = [0] * n_seconds
    yaw = [None] * n_seconds; pitch = [None] * n_seconds; down = [None] * n_seconds
    for s in range(n_seconds):
        b = buckets.get(s)
        if not b or not b.frames or b.found < b.frames * 0.5:
            continue
        face[s] = 1
        yaw[s] = float(np.mean(b.yaw)); pitch[s] = float(np.mean(b.pitch)); down[s] = float(np.mean(b.lookdown))
        motion[s] = round(b.motion, 4); smile_raw[s] = b.smile; blink[s] = b.blinks

    seen = [s for s in range(n_seconds) if face[s]]
    if not seen:
        return dict(face=face, attention=[0] * n_seconds, motion=motion, smile=smile_raw, blink=blink)

    # People face the screen most of the time, so the median pose is "looking at the screen".
    # That makes the result independent of where the camera sits relative to the display.
    yaw0 = float(np.median([yaw[s] for s in seen])); pitch0 = float(np.median([pitch[s] for s in seen]))
    down0 = float(np.median([down[s] for s in seen]))
    attention = [0] * n_seconds
    for s in seen:
        toward = abs(yaw[s] - yaw0) < YAW_LIMIT and abs(pitch[s] - pitch0) < PITCH_LIMIT
        eyes_up = (down[s] - down0) < LOOKDOWN_LIMIT
        attention[s] = 1 if (toward and eyes_up) else 0

    # Smile relative to this viewer's resting face.
    rest = float(np.percentile([smile_raw[s] for s in seen], 20))
    smile = [0.0] * n_seconds
    for s in seen:
        smile[s] = round(min(1.0, max(0.0, (smile_raw[s] - rest) / max(1e-6, 1.0 - rest))), 3)
    return dict(face=face, attention=attention, motion=motion, smile=smile, blink=blink)


def main():
    ap = argparse.ArgumentParser(description="Record one viewer's attention and reactions as numbers.")
    ap.add_argument("--viewer", required=True, help="an id for this viewer, e.g. v01 (avoid real names)")
    ap.add_argument("--film", required=True, help="film or cut name; keep it identical across viewers")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--minutes", type=float, default=None, help="stop after this many minutes")
    ap.add_argument("--out", default="sessions")
    ap.add_argument("--model", default="face_landmarker.task")
    ap.add_argument("--preview", action="store_true", help="show a small status window (distracting; for setup only)")
    ap.add_argument("--video", default=None, help="analyse a recorded video file instead of the webcam")
    ap.add_argument("--no-wait", action="store_true", help="start immediately instead of waiting for Enter")
    a = ap.parse_args()

    options = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=get_model(a.model)),
        running_mode=vision.RunningMode.VIDEO, num_faces=1,
        output_face_blendshapes=True, output_facial_transformation_matrixes=True)
    landmarker = vision.FaceLandmarker.create_from_options(options)

    cap = cv2.VideoCapture(a.video if a.video else a.camera)
    if not cap.isOpened():
        sys.exit("Could not open the camera. Try --camera 1, or check camera permissions for your terminal.")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    if not a.video and not a.no_wait:
        input("Camera ready. Press Enter the moment the film starts... ")
    print("Recording numbers only. Ctrl+C to stop and save.")

    buckets, start, frame_i = {}, time.monotonic(), 0
    prev_nose, prev_blinking, last_print = None, False, -1
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            elapsed = frame_i / fps if a.video else time.monotonic() - start
            frame_i += 1
            if a.minutes and elapsed >= a.minutes * 60:
                break
            sec = int(elapsed)
            b = buckets.setdefault(sec, SecondBucket()); b.frames += 1

            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            res = landmarker.detect_for_video(image, int(elapsed * 1000) + frame_i)  # strictly increasing
            if res.face_landmarks:
                b.found += 1
                lm = res.face_landmarks[0]
                shapes = {c.category_name: c.score for c in res.face_blendshapes[0]}
                y, p = head_angles(res.facial_transformation_matrixes[0])
                b.yaw.append(y); b.pitch.append(p)
                b.lookdown.append((shapes.get("eyeLookDownLeft", 0) + shapes.get("eyeLookDownRight", 0)) / 2)
                b.smile = max(b.smile, (shapes.get("mouthSmileLeft", 0) + shapes.get("mouthSmileRight", 0)) / 2)
                blinking = (shapes.get("eyeBlinkLeft", 0) + shapes.get("eyeBlinkRight", 0)) / 2 > 0.5
                if blinking and not prev_blinking:
                    b.blinks += 1
                prev_blinking = blinking
                width = math.hypot(lm[LEFT_EDGE].x - lm[RIGHT_EDGE].x, lm[LEFT_EDGE].y - lm[RIGHT_EDGE].y) or 1e-6
                nose = (lm[NOSE].x, lm[NOSE].y)
                if prev_nose is not None:
                    b.motion += math.hypot(nose[0] - prev_nose[0], nose[1] - prev_nose[1]) / width
                prev_nose = nose
            else:
                prev_nose = None

            if a.preview:
                txt = "face found" if res.face_landmarks else "NO FACE: check lighting and framing"
                small = cv2.resize(frame, (320, 240)); small[:] = small // 4      # dimmed so it is not a mirror
                cv2.putText(small, txt, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.imshow("Screentest setup", small)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
            if sec != last_print and sec % 60 == 0 and sec:
                last_print = sec
                print(f"  {sec // 60} min recorded")
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        cap.release()
        if a.preview:
            cv2.destroyAllWindows()

    n = (max(buckets) + 1) if buckets else 0
    if n < 60:
        sys.exit("Under a minute recorded, nothing saved.")
    data = summarise(buckets, n)
    session = {"viewer_id": a.viewer, "film": a.film, "dt": 1, **data}
    os.makedirs(a.out, exist_ok=True)
    safe = lambda s: re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")
    path = os.path.join(a.out, f"{safe(a.film)}__{safe(a.viewer)}.json")
    with open(path, "w") as f:
        json.dump(session, f, separators=(",", ":"))
    found = sum(data["face"]); watching = sum(data["attention"])
    print(f"Saved {path}: {n // 60} min {n % 60} s, face found {100 * found // n}% of the time, "
          f"watching {100 * watching // max(1, found)}% of that.")
    if found < n * 0.7:
        print("Face was missing a lot. A dark room is the usual cause: add a dim lamp behind the screen, "
              "or use an infrared webcam.")


if __name__ == "__main__":
    main()
