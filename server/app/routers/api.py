import gzip
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..config import STORAGE_DIR, THUMBS_DIR
from ..db import get_db
from ..models import Video

router = APIRouter(prefix="/api")

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
CHUNK_SIZE = 1024 * 1024


def _range_response(path: str, range_header: str | None, media_type: str) -> StreamingResponse:
    """Video seeking needs 206 Partial Content — Starlette's FileResponse
    doesn't parse Range headers, so <video> can't seek without this."""
    size = os.path.getsize(path)
    start, end = 0, size - 1
    status_code = 200
    m = RANGE_RE.match(range_header) if range_header else None
    if m:
        if m.group(1):
            start = int(m.group(1))
        if m.group(2):
            end = int(m.group(2))
        elif m.group(1):
            end = size - 1
        start, end = max(0, start), min(size - 1, end)
        status_code = 206

    length = end - start + 1

    def stream():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "accept-ranges": "bytes",
        "content-length": str(length),
    }
    if status_code == 206:
        headers["content-range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(stream(), status_code=status_code, media_type=media_type, headers=headers)


@router.get("/videos/{video_id}/file")
def get_file(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "not found")
    return _range_response(video.filename, request.headers.get("range"), "video/mp4")


@router.get("/videos/{video_id}/track")
def get_track(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video or not video.track_path:
        raise HTTPException(404, "track not ready")
    body = (STORAGE_DIR / video.track_path).read_bytes()
    headers = {}
    if "gzip" in request.headers.get("accept-encoding", ""):
        body = gzip.compress(body)
        headers["content-encoding"] = "gzip"
    return Response(body, media_type="application/json", headers=headers)


@router.get("/videos/{video_id}/segments/{n}/thumb")
def get_thumb(video_id: int, n: int):
    path = THUMBS_DIR / str(video_id) / f"{n}.jpg"
    if not path.exists():
        raise HTTPException(404, "no thumbnail")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/videos/{video_id}/segments")
def get_segments(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "not found")
    return [
        {
            "id": s.id,
            "start": s.start_sec,
            "end": s.end_sec,
            "label": s.label,
            "description": s.description,
            "subtitle": s.subtitle,
        }
        for s in video.segments
    ]
