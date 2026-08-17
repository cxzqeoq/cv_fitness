# extract_desc.py — извлечение world-ландмарков позы из видео (офлайн-тест для debug_seg).
# Пишет segtest/data/<name>_wm.json: {duration, fps, rate_hz, frames:[{t, wm: null | [33×{x,y,z,v}]}]}.
# Математика не дублируется: сигнал считает analyze.mjs тем же signature.js, что и браузер.
# Запуск: python tools/extract_desc.py videos/clip1.mp4 [--rate 5]
import argparse
import json
import os
import sys

import cv2
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.vision.core.image import Image, ImageFormat

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "..", "models", "pose_landmarker_lite.task")
DATA = os.path.join(HERE, "..", "data")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="путь к видео")
    ap.add_argument("--rate", type=float, default=5.0, help="сэмплирование, Гц (по умолчанию 5)")
    ap.add_argument("--limit", type=int, default=0, help="лимит собранных кадров (0 = все)")
    args = ap.parse_args()

    name = os.path.splitext(os.path.basename(args.video))[0]
    os.makedirs(DATA, exist_ok=True)
    if not os.path.exists(MODEL):
        sys.exit("модель не найдена: " + MODEL)

    lm = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODEL),
        running_mode=vision.RunningMode.IMAGE, num_poses=1,
        min_pose_detection_confidence=0.5, min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5))

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        sys.exit("не открывается видео: " + args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    dur = total / fps if total else 0
    step = max(1, int(round(fps / args.rate)))

    frames = []
    i = 0
    next_i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i >= next_i:
            next_i = i + step
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            try:
                res = lm.detect(Image(ImageFormat.SRGB, rgb))
                wl = res.pose_world_landmarks
                wm = ([{"x": l.x, "y": l.y, "z": l.z,
                        "v": float(l.visibility) if l.visibility is not None else 1.0}
                       for l in wl[0]] if wl else None)
            except Exception:
                wm = None
            frames.append({"t": i / fps, "wm": wm})
            if len(frames) % 200 == 0:
                print("  %d кадров, t=%d/%d с" % (len(frames), i / fps, dur), flush=True)
            if args.limit and len(frames) >= args.limit:
                break
        i += 1
    cap.release()

    out = {"duration": dur, "fps": fps, "rate_hz": args.rate, "frames": frames}
    path = os.path.join(DATA, name + "_wm.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    print("готово: %s — %d кадров (%.0f с)" % (path, len(frames), dur))


if __name__ == "__main__":
    main()