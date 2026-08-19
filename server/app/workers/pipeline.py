"""Server-side pose pipeline: video -> landmarks -> features -> segments.

Port of the client JS pipeline (model.js -> features.js -> signature.js/seg.js)
to run headless on the server with the `mediapipe` python package.
`signature.py` is the Python port of js/signature.js (motion-signature
segmentation) - see that file's docstring for the algorithm.
"""

import json
from pathlib import Path

import cv2
import mediapipe as mp

from ..config import TRACKS_DIR, THUMBS_DIR
from ..db import SessionLocal
from ..models import Video, Segment, VideoStatus
from . import signature as sig

mp_pose = mp.solutions.pose

TARGET_SAMPLE_FPS = 12  # detect on a subsampled stream; overlay still lerps fine at this rate
PROGRESS_EVERY = 25  # commit progress every N processed frames

# Overlay track keeps only the points the 2D skeleton renderer draws (no z, no
# face/finger/heel points) - this is what actually kills the payload: full 33
# points x {x,y,z,v} keys was ~106MB for a 35-min clip, unusable on a phone.
# Order here must match player.js's TRACK_LM.
TRACK_LM = [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]


def extract_track(video_path: Path, video_id: int, db):
    """Sample the video at ~TARGET_SAMPLE_FPS and run MediaPipe Pose on each sample.

    Returns (frames, sig_frames, duration_sec, source_fps). `frames[i].t` is
    the real timestamp in seconds, so the client player can still line up
    against the full-rate <video> element regardless of the sampling step.
    `sig_frames` carries the world-landmark descriptors signature.py needs
    (image-space landmarks aren't camera-angle invariant, so segmentation
    uses the separate world-landmark output MediaPipe already computes).
    """
    cap = cv2.VideoCapture(str(video_path))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, round(src_fps / TARGET_SAMPLE_FPS))
    sampled_total = (total // step) + 1 if total else 0

    video = db.get(Video, video_id)
    video.frames_total = sampled_total
    video.frames_done = 0
    db.commit()

    frames = []
    sig_frames = []
    with mp_pose.Pose(model_complexity=1, min_detection_confidence=0.5) as pose:
        idx = 0
        done = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = pose.process(rgb)
                # Real decoder PTS, not idx/src_fps: phone footage is often
                # VFR (container's r_frame_rate != avg_frame_rate) - assuming
                # constant spacing drifted up to ~2s against actual playback
                # position on a 35-min clip, growing worse over the video.
                t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                compact = [round(t, 2)]
                if result.pose_landmarks:
                    lms = result.pose_landmarks.landmark
                    for i in TRACK_LM:
                        lm = lms[i]
                        compact += [round(lm.x, 3), round(lm.y, 3), round(lm.visibility, 2)]
                frames.append(compact)

                desc = None
                if result.pose_world_landmarks:
                    wlm = [
                        {"x": lm.x, "y": lm.y, "z": lm.z, "v": lm.visibility}
                        for lm in result.pose_world_landmarks.landmark
                    ]
                    desc = sig.frame_descriptors(wlm)
                sig_frames.append({"time": t, "desc": desc})

                done += 1
                if done % PROGRESS_EVERY == 0:
                    video.frames_done = done
                    db.commit()
            idx += 1

    cap.release()
    video.frames_done = done
    db.commit()

    duration = idx / src_fps if src_fps else 0.0
    return frames, sig_frames, duration, src_fps


def generate_thumbnails(video_path: Path, video_id: int, segs: list[dict]) -> None:
    """One frame per segment (0.3s in, avoids the transition frame right at
    the boundary) - segment n's file is named by its position, matching how
    /1/segments is ordered by start_sec in the admin/watch templates."""
    out_dir = THUMBS_DIR / str(video_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    for s in segs:
        t = min(s["start"] + 0.3, s["end"])
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if ok:
            cv2.imwrite(str(out_dir / f"{s['n']}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    cap.release()


def process_video(video_id: int) -> None:
    db = SessionLocal()
    try:
        video = db.get(Video, video_id)
        if video is None:
            return
        video.status = VideoStatus.processing
        db.commit()

        video_path = Path(video.filename)
        try:
            frames, sig_frames, duration, fps = extract_track(video_path, video_id, db)
        except Exception as exc:  # noqa: BLE001 - surface to admin UI
            video.status = VideoStatus.failed
            video.error = str(exc)
            db.commit()
            return

        track_path = TRACKS_DIR / f"{video.id}.json"
        # separators=(",", ":") - no spaces, matters at this size
        track_path.write_text(json.dumps({"fps": fps, "frames": frames}, separators=(",", ":")))

        segs = sig.segment_video(sig_frames, duration)
        db.query(Segment).filter(Segment.video_id == video.id).delete()
        for s in segs:
            label = f"упражнение {s['n']}" if len(segs) > 1 else "упражнение"
            db.add(Segment(video_id=video.id, start_sec=s["start"], end_sec=s["end"], label=label))

        generate_thumbnails(video_path, video_id, segs)

        video.duration_sec = duration
        video.fps = fps
        video.track_path = str(track_path.relative_to(TRACKS_DIR.parent))
        video.status = VideoStatus.done
        db.commit()
    finally:
        db.close()
