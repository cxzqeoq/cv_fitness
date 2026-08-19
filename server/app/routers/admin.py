import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..config import VIDEOS_DIR, BASE_DIR
from ..db import get_db
from ..models import Video, Segment
from ..workers.pipeline import process_video
from ..workers.describe import describe_video

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    videos = db.query(Video).order_by(Video.created_at.desc()).all()
    return templates.TemplateResponse(
        "admin/index.html", {"request": request, "videos": videos, "active": "videos"}
    )


@router.post("/upload")
def upload(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    ext = Path(file.filename).suffix or ".mp4"
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = VIDEOS_DIR / stored_name
    with dest.open("wb") as out:
        out.write(file.file.read())

    video = Video(filename=str(dest), original_name=file.filename)
    db.add(video)
    db.commit()
    db.refresh(video)

    # FastAPI BackgroundTasks: fine for one worker instance, move to a real
    # queue (rq/celery) once concurrent uploads become common.
    background_tasks.add_task(process_video, video.id)

    return RedirectResponse(url=f"/{video.id}", status_code=303)


@router.get("/watch/{video_id}")
def watch(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    return templates.TemplateResponse("watch.html", {"request": request, "video": video})


@router.get("/{video_id}")
def detail(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    return templates.TemplateResponse(
        "admin/detail.html", {"request": request, "video": video, "active": "videos"}
    )


@router.post("/{video_id}/describe")
def describe(video_id: int, background_tasks: BackgroundTasks):
    background_tasks.add_task(describe_video, video_id)
    return RedirectResponse(url=f"/{video_id}", status_code=303)


@router.post("/{video_id}/segments/{segment_id}")
def update_segment(
    video_id: int,
    segment_id: int,
    description: str = Form(""),
    subtitle: str = Form(""),
    label: str = Form(""),
    db: Session = Depends(get_db),
):
    segment = db.get(Segment, segment_id)
    if segment and segment.video_id == video_id:
        segment.description = description
        segment.subtitle = subtitle
        segment.label = label
        db.commit()
    return RedirectResponse(url=f"/{video_id}", status_code=303)
