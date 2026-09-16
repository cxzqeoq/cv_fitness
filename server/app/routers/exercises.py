from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..comparison import compare_tracks
from ..config import BASE_DIR, STORAGE_DIR
from ..db import get_db
from ..models import (
    Exercise,
    ExerciseStatus,
    Segment,
    SegmentComparison,
    SegmentExercise,
    Video,
    VideoStatus,
)

router = APIRouter(prefix="/exercises")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _redirect(
    *,
    error: str | None = None,
    notice: str | None = None,
    exercise_id: int | None = None,
) -> RedirectResponse:
    params = {}
    if error:
        params["error"] = error
    if notice:
        params["notice"] = notice
    url = "/exercises"
    if params:
        url = f"{url}?{urlencode(params)}"
    if exercise_id is not None:
        url = f"{url}#exercise-{exercise_id}"
    return RedirectResponse(url=url, status_code=303)


def _video_redirect(
    video_id: int,
    segment_id: int,
    *,
    error: str | None = None,
    notice: str | None = None,
) -> RedirectResponse:
    params = {}
    if error:
        params["error"] = error
    if notice:
        params["notice"] = notice
    suffix = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"/app/{video_id}{suffix}#segment-{segment_id}", status_code=303)


def _validated_fields(
    name: str,
    description: str,
    instructions: str,
    angle_tolerance: int,
) -> tuple[str, str | None, str | None, int] | str:
    clean_name = name.strip()
    clean_description = description.strip()
    clean_instructions = instructions.strip()
    if not clean_name or len(clean_name) > 200:
        return "Название обязательно и должно быть короче 200 символов."
    if len(clean_description) > 5000 or len(clean_instructions) > 5000:
        return "Описание и инструкция должны быть короче 5000 символов."
    if not 5 <= angle_tolerance <= 45:
        return "Допуск угла должен быть от 5 до 45 градусов."
    return clean_name, clean_description or None, clean_instructions or None, angle_tolerance


def _segment_video(db: Session, segment_id: int) -> tuple[Segment, Video]:
    segment = db.get(Segment, segment_id)
    video = db.get(Video, segment.video_id) if segment is not None else None
    if segment is None or video is None:
        raise HTTPException(404, "segment not found")
    return segment, video


@router.get("")
def exercise_list(
    request: Request,
    q: str = "",
    state: str = "active",
    error: str = "",
    notice: str = "",
    db: Session = Depends(get_db),
) -> Response:
    q = q.strip()[:200]
    query = db.query(Exercise)
    if state == "active":
        query = query.filter(Exercise.status == ExerciseStatus.active)
    elif state == "archived":
        query = query.filter(Exercise.status == ExerciseStatus.archived)
    elif state != "all":
        state = "active"
        query = query.filter(Exercise.status == ExerciseStatus.active)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.filter(
            or_(
                Exercise.name.ilike(pattern, escape="\\"),
                Exercise.description.ilike(pattern, escape="\\"),
            )
        )
    exercises = query.order_by(Exercise.name, Exercise.id).all()
    references = {}
    reference_ids = [item.reference_segment_id for item in exercises if item.reference_segment_id]
    if reference_ids:
        rows = (
            db.query(Segment, Video)
            .join(Video, Video.id == Segment.video_id)
            .filter(Segment.id.in_(reference_ids))
            .all()
        )
        references = {segment.id: (segment, video) for segment, video in rows}
    usage_counts = {}
    if exercises:
        usage_counts = dict(
            db.query(SegmentExercise.exercise_id, func.count(SegmentExercise.segment_id))
            .filter(SegmentExercise.exercise_id.in_([item.id for item in exercises]))
            .group_by(SegmentExercise.exercise_id)
            .all()
        )
    return templates.TemplateResponse(
        "admin/exercises.html",
        {
            "request": request,
            "active": "exercises",
            "exercises": exercises,
            "references": references,
            "usage_counts": usage_counts,
            "q": q,
            "state": state,
            "error": error[:500],
            "notice": notice[:500],
        },
    )


@router.post("")
def create_exercise(
    name: str = Form(""),
    description: str = Form(""),
    instructions: str = Form(""),
    angle_tolerance: int = Form(15),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validated = _validated_fields(name, description, instructions, angle_tolerance)
    if isinstance(validated, str):
        return _redirect(error=validated)
    clean_name, clean_description, clean_instructions, clean_tolerance = validated
    duplicate = db.query(Exercise).filter(func.lower(Exercise.name) == clean_name.lower()).first()
    if duplicate is not None:
        return _redirect(error="Упражнение с таким названием уже существует.")
    exercise = Exercise(
        name=clean_name,
        description=clean_description,
        instructions=clean_instructions,
        angle_tolerance=clean_tolerance,
    )
    try:
        db.add(exercise)
        db.commit()
        db.refresh(exercise)
    except IntegrityError:
        db.rollback()
        return _redirect(error="Упражнение с таким названием уже существует.")
    return _redirect(notice="Упражнение добавлено.", exercise_id=exercise.id)


@router.post("/segments/{segment_id}")
def assign_segment(
    segment_id: int,
    exercise_id: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    segment, video = _segment_video(db, segment_id)
    link = db.get(SegmentExercise, segment_id)
    db.query(SegmentComparison).filter(SegmentComparison.segment_id == segment_id).delete()
    if not exercise_id:
        if link is not None:
            db.delete(link)
        db.commit()
        return _video_redirect(video.id, segment_id, notice="Упражнение отвязано от сегмента.")
    try:
        parsed_id = int(exercise_id)
    except ValueError:
        return _video_redirect(video.id, segment_id, error="Выберите упражнение из каталога.")
    exercise = db.get(Exercise, parsed_id)
    if exercise is None or exercise.status != ExerciseStatus.active:
        return _video_redirect(video.id, segment_id, error="Упражнение не найдено или находится в архиве.")
    if link is None:
        link = SegmentExercise(segment_id=segment_id, exercise_id=exercise.id)
        db.add(link)
    else:
        link.exercise_id = exercise.id
    db.commit()
    return _video_redirect(video.id, segment_id, notice="Упражнение назначено сегменту.")


@router.post("/{exercise_id}/reference/{segment_id}")
def set_reference(
    exercise_id: int,
    segment_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    exercise = db.get(Exercise, exercise_id)
    segment, video = _segment_video(db, segment_id)
    if exercise is None:
        raise HTTPException(404, "exercise not found")
    if exercise.status != ExerciseStatus.active:
        return _video_redirect(video.id, segment.id, error="Нельзя назначить эталон архивному упражнению.")
    if video.status != VideoStatus.done or not video.track_path:
        return _video_redirect(video.id, segment.id, error="Для эталона нужен готовый трек скелета.")
    existing_reference = (
        db.query(Exercise)
        .filter(
            Exercise.reference_segment_id == segment.id,
            Exercise.id != exercise.id,
        )
        .first()
    )
    if existing_reference is not None:
        return _video_redirect(
            video.id,
            segment.id,
            error=f"Этот сегмент уже служит эталоном упражнения «{existing_reference.name}».",
        )
    exercise.reference_segment_id = segment.id
    link = db.get(SegmentExercise, segment.id)
    if link is None:
        db.add(SegmentExercise(segment_id=segment.id, exercise_id=exercise.id))
    else:
        link.exercise_id = exercise.id
    db.query(SegmentComparison).filter(
        or_(
            SegmentComparison.exercise_id == exercise.id,
            SegmentComparison.segment_id == segment.id,
        )
    ).delete(synchronize_session=False)
    db.commit()
    return _video_redirect(video.id, segment.id, notice="Сегмент назначен эталоном упражнения.")


@router.post("/segments/{segment_id}/compare")
def compare_segment(segment_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    segment, video = _segment_video(db, segment_id)
    link = db.get(SegmentExercise, segment_id)
    exercise = db.get(Exercise, link.exercise_id) if link is not None else None
    reference = db.get(Segment, exercise.reference_segment_id) if exercise and exercise.reference_segment_id else None
    reference_video = db.get(Video, reference.video_id) if reference is not None else None
    if exercise is None:
        return _video_redirect(video.id, segment.id, error="Сначала назначьте упражнение сегменту.")
    if exercise.status != ExerciseStatus.active:
        return _video_redirect(video.id, segment.id, error="Архивное упражнение нельзя сравнивать.")
    if reference is None or reference_video is None:
        return _video_redirect(video.id, segment.id, error="У упражнения ещё нет эталонного сегмента.")
    if not video.track_path or not reference_video.track_path:
        return _video_redirect(video.id, segment.id, error="Для сравнения нужны готовые треки скелета.")
    try:
        result = compare_tracks(
            STORAGE_DIR / reference_video.track_path,
            reference.start_sec,
            reference.end_sec,
            STORAGE_DIR / video.track_path,
            segment.start_sec,
            segment.end_sec,
            exercise.angle_tolerance,
        )
    except ValueError as exc:
        return _video_redirect(video.id, segment.id, error=str(exc))

    comparison = db.get(SegmentComparison, segment.id)
    if comparison is None:
        comparison = SegmentComparison(segment_id=segment.id)
        db.add(comparison)
    comparison.exercise_id = exercise.id
    comparison.reference_segment_id = reference.id
    comparison.score = result["score"]
    comparison.tempo_score = result["tempo_score"]
    comparison.feature_scores = result["feature_scores"]
    comparison.sample_count = result["sample_count"]
    comparison.computed_at = datetime.now(timezone.utc)
    db.commit()
    return _video_redirect(video.id, segment.id, notice="Сравнение с эталоном обновлено.")


@router.post("/{exercise_id}")
def update_exercise(
    exercise_id: int,
    name: str = Form(""),
    description: str = Form(""),
    instructions: str = Form(""),
    angle_tolerance: int = Form(15),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    exercise = db.get(Exercise, exercise_id)
    if exercise is None:
        raise HTTPException(404, "exercise not found")
    validated = _validated_fields(name, description, instructions, angle_tolerance)
    if isinstance(validated, str):
        return _redirect(error=validated, exercise_id=exercise_id)
    clean_name, clean_description, clean_instructions, clean_tolerance = validated
    duplicate = (
        db.query(Exercise)
        .filter(func.lower(Exercise.name) == clean_name.lower(), Exercise.id != exercise_id)
        .first()
    )
    if duplicate is not None:
        return _redirect(error="Упражнение с таким названием уже существует.", exercise_id=exercise_id)
    tolerance_changed = exercise.angle_tolerance != clean_tolerance
    exercise.name = clean_name
    exercise.description = clean_description
    exercise.instructions = clean_instructions
    exercise.angle_tolerance = clean_tolerance
    if tolerance_changed:
        db.query(SegmentComparison).filter(SegmentComparison.exercise_id == exercise.id).delete()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _redirect(error="Упражнение с таким названием уже существует.", exercise_id=exercise_id)
    return _redirect(notice="Упражнение сохранено.", exercise_id=exercise_id)


@router.post("/{exercise_id}/archive")
def archive_exercise(exercise_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    exercise = db.get(Exercise, exercise_id)
    if exercise is None:
        raise HTTPException(404, "exercise not found")
    exercise.status = (
        ExerciseStatus.archived if exercise.status == ExerciseStatus.active else ExerciseStatus.active
    )
    db.commit()
    notice = "Упражнение перемещено в архив." if exercise.status == ExerciseStatus.archived else "Упражнение восстановлено."
    return _redirect(notice=notice, exercise_id=exercise.id)
