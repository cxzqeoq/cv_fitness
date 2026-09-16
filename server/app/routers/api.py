import gzip
import mimetypes
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..config import STORAGE_DIR, THUMBS_DIR
from ..db import get_db
from ..models import (
    AssessmentStatus,
    SegmentAssessment,
    StudentVideo,
    Video,
    VideoAssessment,
    VideoPublication,
    VideoStatus,
)

router = APIRouter(prefix="/api")

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
CHUNK_SIZE = 1024 * 1024


def _range_response(path: str, range_header: str | None) -> StreamingResponse:
    """Stream a file with the Range support required by HTML video seeking."""
    size = os.path.getsize(path)
    start, end = 0, size - 1
    status_code = 200
    match = RANGE_RE.match(range_header) if range_header else None
    if match:
        if match.group(1):
            start = int(match.group(1))
        if match.group(2):
            end = int(match.group(2))
        elif match.group(1):
            end = size - 1
        start, end = max(0, start), min(size - 1, end)
        if start > end:
            raise HTTPException(416, "range not satisfiable")
        status_code = 206

    length = end - start + 1

    def stream():
        with open(path, "rb") as source:
            source.seek(start)
            remaining = length
            while remaining > 0:
                chunk = source.read(min(CHUNK_SIZE, remaining))
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
    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return StreamingResponse(
        stream(),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )


def _track_response(video: Video, request: Request) -> Response:
    if not video.track_path:
        raise HTTPException(404, "track not ready")
    body = (STORAGE_DIR / video.track_path).read_bytes()
    headers = {}
    if "gzip" in request.headers.get("accept-encoding", ""):
        body = gzip.compress(body)
        headers["content-encoding"] = "gzip"
    return Response(body, media_type="application/json", headers=headers)


def _segments_payload(video: Video, db: Session) -> list[dict]:
    video_assessment = db.get(VideoAssessment, video.id)
    assessments = {}
    if video_assessment is not None and video_assessment.status == AssessmentStatus.final:
        segment_ids = [segment.id for segment in video.segments]
        if segment_ids:
            assessments = {
                item.segment_id: item
                for item in db.query(SegmentAssessment)
                .filter(SegmentAssessment.segment_id.in_(segment_ids))
                .all()
            }
    payload = []
    for segment in video.segments:
        assessment = assessments.get(segment.id)
        feedback = None
        if assessment is not None:
            feedback = {
                "technique": assessment.technique,
                "range_of_motion": assessment.range_of_motion,
                "stability": assessment.stability,
                "tempo": assessment.tempo,
                "symmetry": assessment.symmetry,
                "comment": assessment.comment,
            }
        payload.append(
            {
                "id": segment.id,
                "start": segment.start_sec,
                "end": segment.end_sec,
                "label": segment.label,
                "description": segment.description,
                "subtitle": segment.subtitle,
                "coach_feedback": feedback,
            }
        )
    return payload


def _thumbnail_response(video_id: int, number: int) -> FileResponse:
    path = THUMBS_DIR / str(video_id) / f"{number}.jpg"
    if not path.exists():
        raise HTTPException(404, "no thumbnail")
    return FileResponse(path, media_type="image/jpeg")


def _published_video(token: str, db: Session) -> Video:
    publication = (
        db.query(VideoPublication)
        .filter(VideoPublication.token == token)
        .first()
    )
    video = db.get(Video, publication.video_id) if publication is not None else None
    if video is None or video.status != VideoStatus.done:
        raise HTTPException(404, "published video not found")
    return video


@router.get("/videos/{video_id}/file")
def get_file(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "not found")
    return _range_response(video.filename, request.headers.get("range"))


@router.get("/videos/{video_id}/track")
def get_track(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "not found")
    return _track_response(video, request)


@router.get("/videos/{video_id}/segments/{number}/thumb")
def get_thumb(video_id: int, number: int):
    return _thumbnail_response(video_id, number)


@router.get("/videos/{video_id}/segments")
def get_segments(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "not found")
    return _segments_payload(video, db)


@router.get("/public/{token}/file")
def get_public_file(token: str, request: Request, db: Session = Depends(get_db)):
    video = _published_video(token, db)
    return _range_response(video.filename, request.headers.get("range"))


@router.get("/public/{token}/track")
def get_public_track(token: str, request: Request, db: Session = Depends(get_db)):
    return _track_response(_published_video(token, db), request)


@router.get("/public/{token}/segments/{number}/thumb")
def get_public_thumb(
    token: str,
    number: int,
    db: Session = Depends(get_db),
):
    video = _published_video(token, db)
    return _thumbnail_response(video.id, number)


@router.get("/public/{token}/segments")
def get_public_segments(token: str, db: Session = Depends(get_db)):
    return _segments_payload(_published_video(token, db), db)

def _student_video(video_id: int, request: Request, db: Session) -> Video:
    principal = request.state.principal
    assignment = db.get(StudentVideo, video_id)
    video = db.get(Video, video_id)
    if (
        assignment is None
        or assignment.student_id != principal["student_id"]
        or video is None
        or video.status != VideoStatus.done
    ):
        raise HTTPException(404, "video not found")
    return video


@router.get("/student/videos/{video_id}/file")
def get_student_file(
    video_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    video = _student_video(video_id, request, db)
    return _range_response(video.filename, request.headers.get("range"))


@router.get("/student/videos/{video_id}/track")
def get_student_track(
    video_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    return _track_response(_student_video(video_id, request, db), request)


@router.get("/student/videos/{video_id}/segments/{number}/thumb")
def get_student_thumb(
    video_id: int,
    number: int,
    request: Request,
    db: Session = Depends(get_db),
):
    video = _student_video(video_id, request, db)
    return _thumbnail_response(video.id, number)


@router.get("/student/videos/{video_id}/segments")
def get_student_segments(
    video_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    return _segments_payload(_student_video(video_id, request, db), db)
