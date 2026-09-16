import re
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..assignment_workflow import reset_assignment, review_assignment
from ..notification_service import notify_student

from ..config import BASE_DIR
from ..db import get_db
from ..models import (
    SegmentAssessment,
    NotificationEvent,
    Student,
    StudentStatus,
    StudentVideo,
    Video,
    VideoAssessment,
)

router = APIRouter(prefix="/students")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SCORE_FIELDS = ("technique", "range_of_motion", "stability", "tempo", "symmetry")


def _redirect(
    *,
    student_id: int | None = None,
    error: str | None = None,
    notice: str | None = None,
) -> RedirectResponse:
    url = f"/students/{student_id}" if student_id is not None else "/students"
    params = {}
    if error:
        params["error"] = error
    if notice:
        params["notice"] = notice
    if params:
        url = f"{url}?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=303)


def _video_redirect(
    video_id: int,
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
    return RedirectResponse(url=f"/{video_id}{suffix}", status_code=303)


def _parse_date(value: str, label: str) -> date | None | str:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return f"Укажите корректную дату: {label}."
    if parsed > date.today():
        return f"Дата «{label}» не может быть в будущем."
    return parsed


def _validated_student(
    name: str,
    phone: str,
    email: str,
    birth_date: str,
    notes: str,
) -> tuple[str, str | None, str | None, date | None, str | None] | str:
    clean_name = name.strip()
    clean_phone = phone.strip()
    clean_email = email.strip().lower()
    clean_notes = notes.strip()
    if not clean_name or len(clean_name) > 120:
        return "Имя обязательно и должно быть короче 120 символов."
    if len(clean_phone) > 50:
        return "Телефон должен быть короче 50 символов."
    if clean_email and (len(clean_email) > 320 or not _EMAIL_RE.fullmatch(clean_email)):
        return "Укажите корректный email или оставьте поле пустым."
    if len(clean_notes) > 5000:
        return "Заметки должны быть короче 5000 символов."
    parsed_birth_date = _parse_date(birth_date, "дата рождения")
    if isinstance(parsed_birth_date, str):
        return parsed_birth_date
    return (
        clean_name,
        clean_phone or None,
        clean_email or None,
        parsed_birth_date,
        clean_notes or None,
    )


def _assessment_average(assessment: VideoAssessment | None) -> float | None:
    if assessment is None:
        return None
    values = [getattr(assessment, field) for field in _SCORE_FIELDS]
    if any(value is None for value in values):
        return None
    return round(sum(values) / len(values), 1)


@router.get("")
def student_list(
    request: Request,
    q: str = "",
    state: str = "active",
    error: str = "",
    notice: str = "",
    db: Session = Depends(get_db),
) -> Response:
    q = q.strip()[:200]
    query = db.query(Student)
    if state == "active":
        query = query.filter(Student.status == StudentStatus.active)
    elif state == "archived":
        query = query.filter(Student.status == StudentStatus.archived)
    elif state != "all":
        state = "active"
        query = query.filter(Student.status == StudentStatus.active)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.filter(
            or_(
                Student.name.ilike(pattern, escape="\\"),
                Student.phone.ilike(pattern, escape="\\"),
                Student.email.ilike(pattern, escape="\\"),
            )
        )
    students = query.order_by(Student.name, Student.id).limit(300).all()
    counts = {}
    if students:
        counts = dict(
            db.query(StudentVideo.student_id, func.count(StudentVideo.video_id))
            .filter(StudentVideo.student_id.in_([student.id for student in students]))
            .group_by(StudentVideo.student_id)
            .all()
        )
    return templates.TemplateResponse(
        "admin/students.html",
        {
            "request": request,
            "active": "students",
            "students": students,
            "counts": counts,
            "q": q,
            "state": state,
            "error": error[:500],
            "notice": notice[:500],
        },
    )


@router.post("")
def create_student(
    name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    birth_date: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validated = _validated_student(name, phone, email, birth_date, notes)
    if isinstance(validated, str):
        return _redirect(error=validated)
    clean_name, clean_phone, clean_email, parsed_birth_date, clean_notes = validated
    student = Student(
        name=clean_name,
        phone=clean_phone,
        email=clean_email,
        birth_date=parsed_birth_date,
        notes=clean_notes,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return _redirect(student_id=student.id, notice="Ученик добавлен.")


@router.post("/videos/assign")
def assign_video(
    video_id: int = Form(...),
    student_id: str = Form(""),
    exercise_name: str = Form(""),
    training_date: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "video not found")
    clean_exercise = exercise_name.strip()
    if len(clean_exercise) > 200:
        return _video_redirect(video_id, error="Название упражнения должно быть короче 200 символов.")
    parsed_training_date = _parse_date(training_date, "дата тренировки")
    if isinstance(parsed_training_date, str):
        return _video_redirect(video_id, error=parsed_training_date)

    assignment = db.get(StudentVideo, video_id)
    new_student = None
    if student_id:
        try:
            new_student_id = int(student_id)
        except ValueError:
            return _video_redirect(video_id, error="Выберите ученика из списка.")
        new_student = db.get(Student, new_student_id)
        if new_student is None:
            return _video_redirect(video_id, error="Выбранный ученик не найден.")
        if (
            new_student.status == StudentStatus.archived
            and (assignment is None or assignment.student_id != new_student.id)
        ):
            return _video_redirect(video_id, error="Нельзя назначить видео ученику из архива.")

    student_changed = assignment is not None and (
        new_student is None or assignment.student_id != new_student.id
    )
    assignment_created = assignment is None or student_changed
    if student_changed:
        db.query(VideoAssessment).filter(VideoAssessment.video_id == video_id).delete()
        segment_ids = [segment.id for segment in video.segments]
        if segment_ids:
            db.query(SegmentAssessment).filter(
                SegmentAssessment.segment_id.in_(segment_ids)
            ).delete(synchronize_session=False)
        reset_assignment(assignment)

    if new_student is None:
        if assignment is not None:
            db.delete(assignment)
        db.commit()
        return _video_redirect(video_id, notice="Привязка к ученику удалена.")

    if assignment is None:
        assignment = StudentVideo(video_id=video_id, student_id=new_student.id)
        db.add(assignment)
    else:
        assignment.student_id = new_student.id
    assignment.exercise_name = clean_exercise or None
    assignment.training_date = parsed_training_date
    if assignment_created:
        workout_name = assignment.exercise_name or video.original_name
        notify_student(
            db,
            student_id=new_student.id,
            event=NotificationEvent.assignment_created,
            title="Новая тренировка",
            body=f"Тренер назначил «{workout_name}».",
            url=f"/student/videos/{video.id}",
        )
    db.commit()
    notice = "Видео привязано к ученику."
    if student_changed:
        notice += " Предыдущая оценка сброшена."
    return _video_redirect(video_id, notice=notice)


@router.post("/videos/{video_id}/review")
def review_video_assignment(
    video_id: int,
    action: str = Form("save"),
    coach_comment: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    assignment = db.get(StudentVideo, video_id)
    if assignment is None:
        raise HTTPException(404, "assignment not found")
    previous_status = assignment.status
    previous_comment = assignment.coach_comment
    try:
        review_assignment(assignment, action, coach_comment)
    except ValueError as exc:
        return _redirect(student_id=assignment.student_id, error=str(exc))
    event = None
    title = ""
    body = ""
    if action == "complete" and previous_status.value != "completed":
        event = NotificationEvent.assignment_completed
        title = "Тренировка завершена"
        body = "Тренер принял результат и завершил тренировку."
    elif action == "reopen":
        event = NotificationEvent.assignment_reopened
        title = "Тренировка возвращена в работу"
        body = "Тренер просит доработать результат и отправить его повторно."
    elif action == "save" and assignment.coach_comment and assignment.coach_comment != previous_comment:
        event = NotificationEvent.trainer_replied
        title = "Новый комментарий тренера"
        body = assignment.coach_comment
    if event is not None:
        notify_student(
            db,
            student_id=assignment.student_id,
            event=event,
            title=title,
            body=body,
            url=f"/student/videos/{assignment.video_id}",
        )
    db.commit()
    notices = {
        "save": "Комментарий тренера сохранён.",
        "complete": "Тренировка завершена.",
        "reopen": "Тренировка возвращена ученику в работу.",
    }
    return _redirect(
        student_id=assignment.student_id,
        notice=notices[action],
    )


@router.get("/{student_id}")
def student_detail(
    student_id: int,
    request: Request,
    error: str = "",
    notice: str = "",
    db: Session = Depends(get_db),
) -> Response:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(404, "student not found")
    rows = (
        db.query(StudentVideo, Video, VideoAssessment)
        .join(Video, Video.id == StudentVideo.video_id)
        .outerjoin(VideoAssessment, VideoAssessment.video_id == Video.id)
        .filter(StudentVideo.student_id == student_id)
        .order_by(StudentVideo.training_date.desc().nullslast(), Video.created_at.desc())
        .all()
    )
    history = [
        {
            "assignment": assignment,
            "video": video,
            "assessment": assessment,
            "average": _assessment_average(assessment),
        }
        for assignment, video, assessment in rows
    ]
    final_averages = [
        item["average"]
        for item in history
        if item["assessment"] is not None
        and item["assessment"].status.value == "final"
        and item["average"] is not None
    ]
    return templates.TemplateResponse(
        "admin/student_detail.html",
        {
            "request": request,
            "active": "students",
            "student": student,
            "history": history,
            "reviewed_count": len(final_averages),
            "average_score": round(sum(final_averages) / len(final_averages), 1)
            if final_averages
            else None,
            "error": error[:500],
            "notice": notice[:500],
            "submitted_count": sum(
                item["assignment"].status.value == "submitted" for item in history
            ),
            "completed_count": sum(
                item["assignment"].status.value == "completed" for item in history
            ),
        },
    )


@router.post("/{student_id}")
def update_student(
    student_id: int,
    name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    birth_date: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(404, "student not found")
    validated = _validated_student(name, phone, email, birth_date, notes)
    if isinstance(validated, str):
        return _redirect(student_id=student_id, error=validated)
    student.name, student.phone, student.email, student.birth_date, student.notes = validated
    db.commit()
    return _redirect(student_id=student_id, notice="Карточка ученика сохранена.")


@router.post("/{student_id}/archive")
def archive_student(student_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(404, "student not found")
    student.status = (
        StudentStatus.archived if student.status == StudentStatus.active else StudentStatus.active
    )
    db.commit()
    notice = "Ученик перемещён в архив." if student.status == StudentStatus.archived else "Ученик восстановлен."
    return _redirect(student_id=student_id, notice=notice)
