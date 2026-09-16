import json
import math
import secrets
import shutil
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlencode

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import (
    ALLOWED_VIDEO_EXTENSIONS,
    BASE_DIR,
    STORAGE_DIR,
    THUMBS_DIR,
    UPLOAD_CHUNK_BYTES,
    VIDEOS_DIR,
)
from ..db import get_db
from ..exports import build_json_export, build_srt
from ..models import (
    AssessmentStatus,
    Exercise,
    ExerciseStatus,
    Segment,
    SegmentComparison,
    SegmentExercise,
    SegmentAssessment,
    Student,
    StudentStatus,
    StudentVideo,
    Video,
    VideoAssessment,
    VideoPublication,
    VideoStatus,
)
from ..settings_store import get_app_settings
from ..workers.pipeline import generate_thumbnails, process_video
from ..workers.describe import describe_video

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

MIN_SEGMENT_SECONDS = 1.0


def _video_artifacts(video: Video) -> tuple[list[Path], Path]:
    """Resolve only paths contained by managed storage."""
    storage_root = STORAGE_DIR.resolve()
    files = [Path(video.filename).resolve()]
    if video.track_path:
        files.append((STORAGE_DIR / video.track_path).resolve())
    thumbs = (THUMBS_DIR / str(video.id)).resolve()
    if any(not path.is_relative_to(storage_root) for path in [*files, thumbs]):
        raise HTTPException(409, "video has an invalid storage path")
    return files, thumbs


def _remove_artifacts(files: list[Path], thumbs: Path) -> None:
    """Best-effort cleanup after the database no longer references artifacts."""
    for path in files:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    shutil.rmtree(thumbs, ignore_errors=True)

def _invalidate_comparisons(db: Session, segment_ids: list[int]) -> None:
    if not segment_ids:
        return
    db.query(SegmentComparison).filter(
        or_(
            SegmentComparison.segment_id.in_(segment_ids),
            SegmentComparison.reference_segment_id.in_(segment_ids),
        )
    ).delete(synchronize_session=False)


def _validate_video(path: Path) -> None:
    """Reject files that ffprobe cannot identify as video."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        streams = json.loads(result.stdout).get("streams", [])
    except (json.JSONDecodeError, subprocess.TimeoutExpired):
        raise HTTPException(422, "Не удалось проверить видео.") from None
    if result.returncode != 0 or not streams:
        raise HTTPException(422, "Файл не содержит поддерживаемого видеопотока.")


def _format_size_limit(size: int) -> str:
    if size >= 1024**3:
        return f"{size / 1024**3:g} ГБ"
    return f"{size / 1024**2:g} МБ"


def _segment_redirect(
    video_id: int,
    segment_id: int | None = None,
    error: str | None = None,
) -> RedirectResponse:
    url = f"/{video_id}"
    if error:
        url = f"{url}?{urlencode({'segment_error': error})}"
    if segment_id is not None:
        url = f"{url}#segment-{segment_id}"
    return RedirectResponse(url=url, status_code=303)


def _root_redirect(
    *,
    notice: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    params = {}
    if notice:
        params["notice"] = notice
    if error:
        params["error"] = error
    suffix = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"/{suffix}", status_code=303)


def _video_segment(db: Session, video_id: int, segment_id: int) -> tuple[Video, Segment]:
    video = db.get(Video, video_id)
    segment = db.get(Segment, segment_id)
    if video is None or segment is None or segment.video_id != video_id:
        raise HTTPException(404, "segment not found")
    return video, segment


def _ordered_segments(db: Session, video_id: int) -> list[Segment]:
    return (
        db.query(Segment)
        .filter(Segment.video_id == video_id)
        .order_by(Segment.start_sec)
        .all()
    )


def _export_video(db: Session, video_id: int) -> tuple[Video, list[Segment]]:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "video not found")
    if video.status != VideoStatus.done:
        raise HTTPException(409, "video is not ready")
    return video, _ordered_segments(db, video_id)


def _final_assessment(
    db: Session,
    video_id: int,
) -> tuple[VideoAssessment | None, float | None]:
    assessment = db.get(VideoAssessment, video_id)
    if assessment is None or assessment.status != AssessmentStatus.final:
        return None, None
    values = [
        assessment.technique,
        assessment.range_of_motion,
        assessment.stability,
        assessment.tempo,
        assessment.symmetry,
    ]
    average = round(sum(values) / len(values), 1) if all(value is not None for value in values) else None
    return assessment, average



def _prepare_reprocess(db: Session, video: Video) -> tuple[list[Path], Path]:
    if video.status not in (VideoStatus.done, VideoStatus.failed):
        raise HTTPException(409, "video is already queued or processing")
    source = Path(video.filename).resolve()
    if not source.is_file():
        raise HTTPException(409, "source video is missing")
    files, thumbs = _video_artifacts(video)
    video.status = VideoStatus.pending
    video.error = None
    video.frames_total = None
    video.frames_done = None
    video.track_path = None
    db.query(VideoAssessment).filter(VideoAssessment.video_id == video.id).delete()
    segment_ids = [segment.id for segment in video.segments]
    if segment_ids:
        db.query(SegmentAssessment).filter(
            SegmentAssessment.segment_id.in_(segment_ids)
        ).delete(synchronize_session=False)
    return [path for path in files if path != source], thumbs

def _refresh_segment_thumbnails(db: Session, video: Video) -> None:
    segments = _ordered_segments(db, video.id)
    shutil.rmtree(THUMBS_DIR / str(video.id), ignore_errors=True)
    generate_thumbnails(
        Path(video.filename),
        video.id,
        [
            {"n": index, "start": segment.start_sec, "end": segment.end_sec}
            for index, segment in enumerate(segments, start=1)
        ],
    )


def _combined_text(left: str | None, right: str | None, separator: str) -> str | None:
    values = [value.strip() for value in (left, right) if value and value.strip()]
    if not values:
        return None
    if len(values) == 2 and values[0] != values[1]:
        return separator.join(values)
    return values[0]


@router.get("/")
def index(
    request: Request,
    q: str = "",
    notice: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    q = q.strip()[:200]
    query = db.query(Video)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(Video.original_name.ilike(f"%{escaped}%", escape="\\"))
    videos = query.order_by(Video.created_at.desc()).limit(200).all()
    has_active = any(
        video.status in (VideoStatus.pending, VideoStatus.processing)
        for video in videos
    )
    status_counts = {status.value: 0 for status in VideoStatus}
    for video in videos:
        status_counts[video.status.value] += 1
    settings = get_app_settings(db)
    return templates.TemplateResponse(
        "admin/index.html",
        {
            "request": request,
            "videos": videos,
            "active": "videos",
            "q": q,
            "has_active": has_active,
            "status_counts": status_counts,
            "max_upload_bytes": settings.max_upload_bytes,
            "max_upload_label": _format_size_limit(settings.max_upload_bytes),
            "notice": notice[:500],
            "error": error[:500],
        },
    )


@router.post("/upload")
async def upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    original_name = Path(file.filename or "").name
    if not original_name:
        raise HTTPException(400, "Выберите видеофайл.")
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(415, "Поддерживаются MP4, MOV, M4V и WebM.")
    settings = get_app_settings(db)

    dest = VIDEOS_DIR / f"{uuid.uuid4().hex}{ext}"
    size = 0
    try:
        with dest.open("xb") as out:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    limit = _format_size_limit(settings.max_upload_bytes)
                    raise HTTPException(413, f"Размер видео превышает {limit}.")
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "Нельзя загрузить пустой файл.")
        _validate_video(dest)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    video = Video(filename=str(dest), original_name=original_name)
    try:
        db.add(video)
        db.commit()
        db.refresh(video)
    except Exception:
        db.rollback()
        dest.unlink(missing_ok=True)
        raise

    # BackgroundTasks is sufficient for one worker; use an external queue
    # before enabling concurrent worker processes.
    background_tasks.add_task(process_video, video.id)
    return RedirectResponse(url=f"/{video.id}", status_code=303)


@router.post("/bulk")
def bulk_videos(
    request: Request,
    background_tasks: BackgroundTasks,
    action: str = Form(...),
    video_ids: list[int] | None = Form(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    selected_ids = list(dict.fromkeys(video_ids or []))
    if not selected_ids:
        return _root_redirect(error="Выберите хотя бы одно видео.")
    if len(selected_ids) > 200:
        return _root_redirect(error="За один раз можно выбрать не больше 200 видео.")
    role = request.state.principal["role"]
    if action == "delete" and role != "owner":
        raise HTTPException(403, "forbidden")
    if action == "publish" and role not in {"owner", "manager"}:
        raise HTTPException(403, "forbidden")

    videos = db.query(Video).filter(Video.id.in_(selected_ids)).all()

    if action == "publish":
        published_ids = {
            publication.video_id
            for publication in db.query(VideoPublication)
            .filter(VideoPublication.video_id.in_(selected_ids))
            .all()
        }
        changed = 0
        for video in videos:
            if video.status != VideoStatus.done or video.id in published_ids:
                continue
            db.add(
                VideoPublication(
                    video_id=video.id,
                    token=secrets.token_urlsafe(24),
                )
            )
            changed += 1
        db.commit()
        skipped = len(selected_ids) - changed
        if not changed:
            return _root_redirect(error="Нет готовых неопубликованных видео в выбранных.")
        notice = f"Опубликовано видео: {changed}."
        if skipped:
            notice += f" Пропущено: {skipped}."
        return _root_redirect(notice=notice)

    if action == "reprocess":
        artifacts: list[tuple[list[Path], Path]] = []
        queued_ids: list[int] = []
        for video in videos:
            if video.status not in (VideoStatus.done, VideoStatus.failed):
                continue
            if not Path(video.filename).is_file():
                continue
            track_files, thumbs = _prepare_reprocess(db, video)
            artifacts.append((track_files, thumbs))
            queued_ids.append(video.id)
        db.commit()
        for files, thumbs in artifacts:
            _remove_artifacts(files, thumbs)
        for video_id in queued_ids:
            background_tasks.add_task(process_video, video_id)
        skipped = len(selected_ids) - len(queued_ids)
        if not queued_ids:
            return _root_redirect(error="Нет видео, которые можно обработать повторно.")
        notice = f"Поставлено в очередь: {len(queued_ids)}."
        if skipped:
            notice += f" Пропущено: {skipped}."
        return _root_redirect(notice=notice)

    if action == "delete":
        artifacts: list[tuple[list[Path], Path]] = []
        deleted = 0
        for video in videos:
            if video.status in (VideoStatus.pending, VideoStatus.processing):
                continue
            files, thumbs = _video_artifacts(video)
            artifacts.append((files, thumbs))
            db.delete(video)
            deleted += 1
        db.commit()
        for files, thumbs in artifacts:
            _remove_artifacts(files, thumbs)
        skipped = len(selected_ids) - deleted
        if not deleted:
            return _root_redirect(error="Нет завершённых видео, которые можно удалить.")
        notice = f"Удалено видео: {deleted}."
        if skipped:
            notice += f" Пропущено: {skipped}."
        return _root_redirect(notice=notice)

    raise HTTPException(400, "unknown bulk action")


@router.post("/{video_id}/reprocess")
def reprocess(
    video_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "video not found")
    track_files, thumbs = _prepare_reprocess(db, video)
    db.commit()
    _remove_artifacts(track_files, thumbs)
    background_tasks.add_task(process_video, video.id)
    return RedirectResponse(url=f"/{video.id}", status_code=303)


@router.post("/{video_id}/delete")
def delete_video(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "video not found")
    if video.status in (VideoStatus.pending, VideoStatus.processing):
        raise HTTPException(409, "cannot delete a video while it is processing")

    files, thumbs = _video_artifacts(video)
    db.delete(video)
    db.commit()
    _remove_artifacts(files, thumbs)
    return RedirectResponse(url="/", status_code=303)


@router.get("/preview/{video_id}")
def preview_watch(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None or video.status != VideoStatus.done:
        raise HTTPException(404, "video not ready")
    settings = get_app_settings(db)
    assessment, assessment_average = _final_assessment(db, video.id)
    return templates.TemplateResponse(
        "watch.html",
        {
            "request": request,
            "video": video,
            "api_base": f"/api/videos/{video.id}",
            "is_preview": True,
            "public_url": None,
            "show_skeleton": settings.show_skeleton,
            "coach_assessment": assessment,
            "assessment_average": assessment_average,
        },
    )


@router.get("/watch/{token}", name="public_watch")
def public_watch(token: str, request: Request, db: Session = Depends(get_db)):
    publication = (
        db.query(VideoPublication)
        .filter(VideoPublication.token == token)
        .first()
    )
    video = db.get(Video, publication.video_id) if publication is not None else None
    if video is None or video.status != VideoStatus.done:
        raise HTTPException(404, "published video not found")
    settings = get_app_settings(db)
    assessment, assessment_average = _final_assessment(db, video.id)
    return templates.TemplateResponse(
        "watch.html",
        {
            "request": request,
            "video": video,
            "api_base": f"/api/public/{publication.token}",
            "is_preview": False,
            "public_url": str(request.url),
            "show_skeleton": settings.show_skeleton,
            "coach_assessment": assessment,
            "assessment_average": assessment_average,
        },
    )


@router.post("/{video_id}/publish")
def publish_video(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "video not found")
    if video.status != VideoStatus.done:
        raise HTTPException(409, "only completed videos can be published")
    publication = db.get(VideoPublication, video_id)
    if publication is None:
        publication = VideoPublication(
            video_id=video_id,
            token=secrets.token_urlsafe(24),
        )
        db.add(publication)
        db.commit()
    return RedirectResponse(url=f"/{video_id}", status_code=303)


@router.post("/{video_id}/unpublish")
def unpublish_video(video_id: int, db: Session = Depends(get_db)):
    publication = db.get(VideoPublication, video_id)
    if publication is not None:
        db.delete(publication)
        db.commit()
    return RedirectResponse(url=f"/{video_id}", status_code=303)


@router.get("/{video_id}/export.srt")
def export_srt(video_id: int, db: Session = Depends(get_db)) -> Response:
    video, segments = _export_video(db, video_id)
    return Response(
        build_srt(segments).encode("utf-8-sig"),
        media_type="application/x-subrip",
        headers={
            "Content-Disposition": f'attachment; filename="video-{video.id}.srt"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{video_id}/export.json")
def export_json(video_id: int, db: Session = Depends(get_db)) -> Response:
    video, segments = _export_video(db, video_id)
    body = json.dumps(
        build_json_export(video, segments),
        ensure_ascii=False,
        indent=2,
    ).encode()
    return Response(
        body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="video-{video.id}.json"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{video_id}")
def detail(
    video_id: int,
    request: Request,
    segment_error: str = "",
    error: str = "",
    notice: str = "",
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)
    publication = db.get(VideoPublication, video_id) if video is not None else None
    assignment = db.get(StudentVideo, video_id) if video is not None else None
    assigned_student = (
        db.get(Student, assignment.student_id) if assignment is not None else None
    )
    students = (
        db.query(Student)
        .filter(Student.status == StudentStatus.active)
        .order_by(Student.name, Student.id)
        .all()
        if video is not None
        else []
    )
    if (
        assigned_student is not None
        and assigned_student.status == StudentStatus.archived
        and all(student.id != assigned_student.id for student in students)
    ):
        students.append(assigned_student)
    assessment = db.get(VideoAssessment, video_id) if video is not None else None
    segment_assessments = {}
    if video is not None and video.segments:
        segment_assessments = {
            item.segment_id: item
            for item in db.query(SegmentAssessment)
            .filter(SegmentAssessment.segment_id.in_([segment.id for segment in video.segments]))
            .all()
        }
    exercises = []
    segment_exercises = {}
    comparisons = {}
    exercise_by_id = {}
    if video is not None:
        exercises = (
            db.query(Exercise)
            .filter(Exercise.status == ExerciseStatus.active)
            .order_by(Exercise.name, Exercise.id)
            .all()
        )
        if video.segments:
            segment_ids = [segment.id for segment in video.segments]
            segment_exercises = {
                item.segment_id: item
                for item in db.query(SegmentExercise)
                .filter(SegmentExercise.segment_id.in_(segment_ids))
                .all()
            }
            comparisons = {
                item.segment_id: item
                for item in db.query(SegmentComparison)
                .filter(SegmentComparison.segment_id.in_(segment_ids))
                .all()
            }
            linked_ids = {item.exercise_id for item in segment_exercises.values()}
            known_ids = {item.id for item in exercises}
            if linked_ids - known_ids:
                exercises.extend(
                    db.query(Exercise)
                    .filter(Exercise.id.in_(linked_ids - known_ids))
                    .order_by(Exercise.name, Exercise.id)
                    .all()
                )
        exercise_by_id = {item.id: item for item in exercises}
    public_url = (
        str(request.url_for("public_watch", token=publication.token))
        if publication is not None
        else None
    )
    return templates.TemplateResponse(
        "admin/detail.html",
        {
            "request": request,
            "video": video,
            "active": "videos",
            "segment_error": segment_error[:500],
            "publication": publication,
            "public_url": public_url,
            "assignment": assignment,
            "assigned_student": assigned_student,
            "students": students,
            "assessment": assessment,
            "segment_assessments": segment_assessments,
            "exercises": exercises,
            "exercise_by_id": exercise_by_id,
            "segment_exercises": segment_exercises,
            "comparisons": comparisons,
            "comparison_features": (
                ("left_elbow", "Левый локоть"),
                ("right_elbow", "Правый локоть"),
                ("left_knee", "Левое колено"),
                ("right_knee", "Правое колено"),
                ("left_hip", "Левое бедро"),
                ("right_hip", "Правое бедро"),
                ("torso_tilt", "Наклон корпуса"),
                ("arm_spread", "Размах рук"),
            ),
            "assessment_status": AssessmentStatus,
            "assessment_criteria": (
                ("technique", "Техника"),
                ("range_of_motion", "Амплитуда"),
                ("stability", "Стабильность"),
                ("tempo", "Темп"),
                ("symmetry", "Симметрия"),
            ),
            "error": error[:500],
            "notice": notice[:500],
        },
    )


@router.post("/{video_id}/describe")
def describe(video_id: int, background_tasks: BackgroundTasks):
    background_tasks.add_task(describe_video, video_id)
    return RedirectResponse(url=f"/{video_id}", status_code=303)


@router.post("/{video_id}/segments/{segment_id}")
def update_segment(
    video_id: int,
    segment_id: int,
    start_sec: float = Form(...),
    end_sec: float = Form(...),
    description: str = Form(""),
    subtitle: str = Form(""),
    label: str = Form(""),
    db: Session = Depends(get_db),
):
    video, segment = _video_segment(db, video_id, segment_id)
    if video.status != VideoStatus.done or video.duration_sec is None:
        return _segment_redirect(video_id, segment_id, "Сегменты доступны после обработки видео.")
    if not math.isfinite(start_sec) or not math.isfinite(end_sec):
        return _segment_redirect(video_id, segment_id, "Границы должны быть числами.")

    segments = _ordered_segments(db, video_id)
    index = next(i for i, item in enumerate(segments) if item.id == segment_id)
    start = round(start_sec, 3)
    end = round(end_sec, 3)
    duration = video.duration_sec
    if index == 0:
        if abs(start) > 0.02:
            return _segment_redirect(video_id, segment_id, "Первый сегмент должен начинаться с 0:00.")
        start = 0.0
    if index == len(segments) - 1:
        if abs(end - duration) > 0.02:
            return _segment_redirect(video_id, segment_id, "Последний сегмент должен заканчиваться вместе с видео.")
        end = duration
    if start < 0 or end > duration + 0.02 or end - start < MIN_SEGMENT_SECONDS:
        return _segment_redirect(video_id, segment_id, "Минимальная длина сегмента — 1 секунда.")

    previous = segments[index - 1] if index > 0 else None
    following = segments[index + 1] if index + 1 < len(segments) else None
    if previous is not None and start - previous.start_sec < MIN_SEGMENT_SECONDS:
        return _segment_redirect(video_id, segment_id, "Предыдущий сегмент станет короче 1 секунды.")
    if following is not None and following.end_sec - end < MIN_SEGMENT_SECONDS:
        return _segment_redirect(video_id, segment_id, "Следующий сегмент станет короче 1 секунды.")

    boundary_changed = start != segment.start_sec or end != segment.end_sec
    segment.start_sec = start
    segment.end_sec = end
    segment.label = label.strip()[:200] or None
    segment.description = description.strip()[:10_000] or None
    segment.subtitle = subtitle.strip()[:10_000] or None
    if previous is not None:
        previous.end_sec = start
    if following is not None:
        following.start_sec = end
    if boundary_changed:
        _invalidate_comparisons(
            db,
            [
                item.id
                for item in (previous, segment, following)
                if item is not None
            ],
        )
    db.commit()
    if boundary_changed:
        _refresh_segment_thumbnails(db, video)
    return _segment_redirect(video_id, segment_id)


@router.post("/{video_id}/segments/{segment_id}/split")
def split_segment(
    video_id: int,
    segment_id: int,
    at_sec: float = Form(...),
    db: Session = Depends(get_db),
):
    video, segment = _video_segment(db, video_id, segment_id)
    if video.status != VideoStatus.done:
        return _segment_redirect(video_id, segment_id, "Сегменты доступны после обработки видео.")
    if not math.isfinite(at_sec):
        return _segment_redirect(video_id, segment_id, "Точка разделения должна быть числом.")

    split_at = round(at_sec, 3)
    if (
        split_at - segment.start_sec < MIN_SEGMENT_SECONDS
        or segment.end_sec - split_at < MIN_SEGMENT_SECONDS
    ):
        return _segment_redirect(
            video_id,
            segment_id,
            "После разделения обе части должны быть не короче 1 секунды.",
        )

    old_end = segment.end_sec
    segment.end_sec = split_at
    new_segment = Segment(
        video_id=video_id,
        start_sec=split_at,
        end_sec=old_end,
        label=segment.label,
        description=segment.description,
        subtitle=segment.subtitle,
    )
    db.add(new_segment)
    _invalidate_comparisons(db, [segment.id])
    db.commit()
    db.refresh(new_segment)
    _refresh_segment_thumbnails(db, video)
    return _segment_redirect(video_id, new_segment.id)


@router.post("/{video_id}/segments/{segment_id}/merge-next")
def merge_segment_with_next(
    video_id: int,
    segment_id: int,
    db: Session = Depends(get_db),
):
    video, segment = _video_segment(db, video_id, segment_id)
    if video.status != VideoStatus.done:
        return _segment_redirect(video_id, segment_id, "Сегменты доступны после обработки видео.")
    segments = _ordered_segments(db, video_id)
    index = next(i for i, item in enumerate(segments) if item.id == segment_id)
    if index == len(segments) - 1:
        return _segment_redirect(video_id, segment_id, "У последнего сегмента нет следующего.")

    following = segments[index + 1]
    segment.end_sec = following.end_sec
    segment.label = _combined_text(segment.label, following.label, " / ")
    segment.description = _combined_text(segment.description, following.description, "\n\n")
    segment.subtitle = _combined_text(segment.subtitle, following.subtitle, "\n\n")
    db.delete(following)
    _invalidate_comparisons(db, [segment.id, following.id])
    db.commit()
    _refresh_segment_thumbnails(db, video)
    return _segment_redirect(video_id, segment_id)


@router.post("/{video_id}/segments/{segment_id}/delete")
def delete_segment(
    video_id: int,
    segment_id: int,
    db: Session = Depends(get_db),
):
    video, segment = _video_segment(db, video_id, segment_id)
    if video.status != VideoStatus.done:
        return _segment_redirect(video_id, segment_id, "Сегменты доступны после обработки видео.")
    segments = _ordered_segments(db, video_id)
    if len(segments) == 1:
        return _segment_redirect(video_id, segment_id, "Нельзя удалить единственный сегмент.")

    index = next(i for i, item in enumerate(segments) if item.id == segment_id)
    if index > 0:
        neighbor = segments[index - 1]
        neighbor.end_sec = segment.end_sec
    else:
        neighbor = segments[1]
        neighbor.start_sec = segment.start_sec
    db.delete(segment)
    _invalidate_comparisons(db, [segment.id, neighbor.id])
    db.commit()
    _refresh_segment_thumbnails(db, video)
    return _segment_redirect(video_id, neighbor.id)
