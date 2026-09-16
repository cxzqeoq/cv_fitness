from datetime import date, datetime, time, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..db import get_db
from ..models import (
    Enrollment,
    EnrollmentStatus,
    Exercise,
    ExerciseStatus,
    Lesson,
    LessonExercise,
    Program,
    ProgramStatus,
    Student,
    StudentStatus,
)
from ..program_workflow import clone_program, enroll_student, publish_program

router = APIRouter(prefix="/programs")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _redirect(
    program_id: int | None = None,
    *,
    error: str | None = None,
    notice: str | None = None,
) -> RedirectResponse:
    params = {}
    if error:
        params["error"] = error
    if notice:
        params["notice"] = notice
    path = f"/programs/{program_id}" if program_id is not None else "/programs"
    suffix = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"{path}{suffix}", status_code=303)


def _program(db: Session, program_id: int) -> Program:
    program = db.get(Program, program_id)
    if program is None:
        raise HTTPException(404, "program not found")
    return program


def _draft(program: Program) -> str | None:
    if program.status != ProgramStatus.draft:
        return "Опубликованная программа неизменяема. Создайте копию для редактирования."
    return None


def _clean_text(value: str, limit: int, label: str, *, required: bool = False) -> str | None:
    clean = value.strip()
    if required and not clean:
        raise ValueError(f"Поле «{label}» обязательно.")
    if len(clean) > limit:
        raise ValueError(f"Поле «{label}» должно быть короче {limit} символов.")
    return clean or None


def _optional_positive(value: int) -> int | None:
    return value if value > 0 else None


@router.get("")
def program_list(
    request: Request,
    error: str = "",
    notice: str = "",
    db: Session = Depends(get_db),
) -> Response:
    programs = db.query(Program).order_by(Program.created_at.desc(), Program.id.desc()).all()
    enrollment_counts = dict(
        db.query(Enrollment.program_id, func.count(Enrollment.id))
        .group_by(Enrollment.program_id)
        .all()
    )
    return templates.TemplateResponse(
        "admin/programs.html",
        {
            "request": request,
            "active": "programs",
            "programs": programs,
            "enrollment_counts": enrollment_counts,
            "error": error[:500],
            "notice": notice[:500],
        },
    )


@router.post("")
def create_program(
    title: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        clean_title = _clean_text(title, 200, "Название", required=True)
        clean_description = _clean_text(description, 5000, "Описание")
    except ValueError as exc:
        return _redirect(error=str(exc))
    program = Program(title=clean_title, description=clean_description)
    db.add(program)
    db.commit()
    db.refresh(program)
    return _redirect(program.id, notice="Черновик программы создан.")


@router.get("/{program_id}")
def program_detail(
    program_id: int,
    request: Request,
    error: str = "",
    notice: str = "",
    db: Session = Depends(get_db),
) -> Response:
    program = _program(db, program_id)
    exercises = (
        db.query(Exercise)
        .filter(Exercise.status == ExerciseStatus.active)
        .order_by(Exercise.name, Exercise.id)
        .all()
    )
    students = (
        db.query(Student)
        .filter(Student.status == StudentStatus.active)
        .order_by(Student.name, Student.id)
        .all()
    )
    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.program_id == program.id)
        .order_by(Enrollment.created_at.desc(), Enrollment.id.desc())
        .all()
    )
    return templates.TemplateResponse(
        "admin/program_detail.html",
        {
            "request": request,
            "active": "programs",
            "program": program,
            "exercises": exercises,
            "students": students,
            "enrollments": enrollments,
            "error": error[:500],
            "notice": notice[:500],
            "today": date.today().isoformat(),
        },
    )


@router.post("/{program_id}")
def update_program(
    program_id: int,
    title: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    program = _program(db, program_id)
    if error := _draft(program):
        return _redirect(program.id, error=error)
    try:
        program.title = _clean_text(title, 200, "Название", required=True)
        program.description = _clean_text(description, 5000, "Описание")
    except ValueError as exc:
        return _redirect(program.id, error=str(exc))
    db.commit()
    return _redirect(program.id, notice="Программа сохранена.")

@router.post("/{program_id}/delete")
def delete_program(program_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    program = _program(db, program_id)
    if error := _draft(program):
        return _redirect(program.id, error=error)
    db.delete(program)
    db.commit()
    return _redirect(notice="Черновик программы удалён.")




@router.post("/{program_id}/lessons")
def create_lesson(
    program_id: int,
    title: str = Form(""),
    content: str = Form(""),
    unlock_offset_days: int = Form(0),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    program = _program(db, program_id)
    if error := _draft(program):
        return _redirect(program.id, error=error)
    try:
        clean_title = _clean_text(title, 200, "Название урока", required=True)
        clean_content = _clean_text(content, 10000, "Содержание")
        if not 0 <= unlock_offset_days <= 3650:
            raise ValueError("День открытия должен быть от 0 до 3650.")
    except ValueError as exc:
        return _redirect(program.id, error=str(exc))
    position = max((lesson.position for lesson in program.lessons), default=0) + 1
    program.lessons.append(
        Lesson(
            position=position,
            title=clean_title,
            content=clean_content,
            unlock_offset_days=unlock_offset_days,
        )
    )
    db.commit()
    return _redirect(program.id, notice="Урок добавлен.")


@router.post("/{program_id}/lessons/{lesson_id}")
def update_lesson(
    program_id: int,
    lesson_id: int,
    title: str = Form(""),
    content: str = Form(""),
    unlock_offset_days: int = Form(0),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    program = _program(db, program_id)
    lesson = db.get(Lesson, lesson_id)
    if lesson is None or lesson.program_id != program.id:
        raise HTTPException(404, "lesson not found")
    if error := _draft(program):
        return _redirect(program.id, error=error)
    try:
        lesson.title = _clean_text(title, 200, "Название урока", required=True)
        lesson.content = _clean_text(content, 10000, "Содержание")
        if not 0 <= unlock_offset_days <= 3650:
            raise ValueError("День открытия должен быть от 0 до 3650.")
        lesson.unlock_offset_days = unlock_offset_days
    except ValueError as exc:
        return _redirect(program.id, error=str(exc))
    db.commit()
    return _redirect(program.id, notice="Урок сохранён.")


@router.post("/{program_id}/lessons/{lesson_id}/delete")
def delete_lesson(
    program_id: int,
    lesson_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    program = _program(db, program_id)
    lesson = db.get(Lesson, lesson_id)
    if lesson is None or lesson.program_id != program.id:
        raise HTTPException(404, "lesson not found")
    if error := _draft(program):
        return _redirect(program.id, error=error)
    db.delete(lesson)
    db.flush()
    db.commit()
    return _redirect(program.id, notice="Урок удалён.")


@router.post("/{program_id}/lessons/{lesson_id}/exercises")
def add_lesson_exercise(
    program_id: int,
    lesson_id: int,
    exercise_id: int = Form(...),
    instructions: str = Form(""),
    target_sets: int = Form(0),
    target_reps: int = Form(0),
    target_duration_sec: int = Form(0),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    program = _program(db, program_id)
    lesson = db.get(Lesson, lesson_id)
    exercise = db.get(Exercise, exercise_id)
    if lesson is None or lesson.program_id != program.id:
        raise HTTPException(404, "lesson not found")
    if error := _draft(program):
        return _redirect(program.id, error=error)
    if exercise is None or exercise.status != ExerciseStatus.active:
        return _redirect(program.id, error="Выберите активное упражнение.")
    try:
        clean_instructions = _clean_text(instructions, 5000, "Инструкция")
        targets = (target_sets, target_reps, target_duration_sec)
        if any(value < 0 or value > 10000 for value in targets):
            raise ValueError("Целевые значения должны быть от 0 до 10000.")
    except ValueError as exc:
        return _redirect(program.id, error=str(exc))
    position = max((item.position for item in lesson.exercises), default=0) + 1
    lesson.exercises.append(
        LessonExercise(
            exercise_id=exercise.id,
            position=position,
            instructions=clean_instructions,
            target_sets=_optional_positive(target_sets),
            target_reps=_optional_positive(target_reps),
            target_duration_sec=_optional_positive(target_duration_sec),
            reference_segment_id=exercise.reference_segment_id,
            is_required=True,
        )
    )
    db.commit()
    return _redirect(program.id, notice="Упражнение добавлено в урок.")


@router.post("/{program_id}/items/{item_id}")
def update_lesson_exercise(
    program_id: int,
    item_id: int,
    instructions: str = Form(""),
    target_sets: int = Form(0),
    target_reps: int = Form(0),
    target_duration_sec: int = Form(0),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    program = _program(db, program_id)
    item = db.get(LessonExercise, item_id)
    if item is None or item.lesson.program_id != program.id:
        raise HTTPException(404, "lesson exercise not found")
    if error := _draft(program):
        return _redirect(program.id, error=error)
    try:
        item.instructions = _clean_text(instructions, 5000, "Инструкция")
        targets = (target_sets, target_reps, target_duration_sec)
        if any(value < 0 or value > 10000 for value in targets):
            raise ValueError("Целевые значения должны быть от 0 до 10000.")
        item.target_sets = _optional_positive(target_sets)
        item.target_reps = _optional_positive(target_reps)
        item.target_duration_sec = _optional_positive(target_duration_sec)
    except ValueError as exc:
        return _redirect(program.id, error=str(exc))
    db.commit()
    return _redirect(program.id, notice="Параметры упражнения сохранены.")


@router.post("/{program_id}/items/{item_id}/delete")
def delete_lesson_exercise(
    program_id: int,
    item_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    program = _program(db, program_id)
    item = db.get(LessonExercise, item_id)
    if item is None or item.lesson.program_id != program.id:
        raise HTTPException(404, "lesson exercise not found")
    if error := _draft(program):
        return _redirect(program.id, error=error)
    db.delete(item)
    db.flush()
    db.commit()
    return _redirect(program.id, notice="Упражнение удалено из урока.")


@router.post("/{program_id}/publish")
def publish(program_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    program = _program(db, program_id)
    try:
        publish_program(program)
    except ValueError as exc:
        return _redirect(program.id, error=str(exc))
    db.commit()
    return _redirect(program.id, notice="Программа опубликована и теперь неизменяема.")


@router.post("/{program_id}/archive")
def archive(program_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    program = _program(db, program_id)
    if program.status != ProgramStatus.published:
        return _redirect(program.id, error="Архивировать можно только опубликованную программу.")
    program.status = ProgramStatus.archived
    program.archived_at = datetime.now(timezone.utc)
    db.commit()
    return _redirect(program.id, notice="Программа перенесена в архив.")


@router.post("/{program_id}/clone")
def clone(program_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    program = _program(db, program_id)
    try:
        copied = clone_program(db, program)
    except ValueError as exc:
        return _redirect(program.id, error=str(exc))
    db.commit()
    return _redirect(copied.id, notice="Создан независимый черновик программы.")


@router.post("/{program_id}/enroll")
def enroll(
    program_id: int,
    student_id: int = Form(...),
    starts_on: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    program = _program(db, program_id)
    student = db.get(Student, student_id)
    if student is None or student.status != StudentStatus.active:
        return _redirect(program.id, error="Выберите активного ученика.")
    duplicate = (
        db.query(Enrollment)
        .filter(
            Enrollment.program_id == program.id,
            Enrollment.student_id == student.id,
            Enrollment.status.in_([EnrollmentStatus.active, EnrollmentStatus.paused]),
        )
        .first()
    )
    if duplicate is not None:
        return _redirect(program.id, error="Ученик уже проходит эту программу.")
    try:
        parsed_date = date.fromisoformat(starts_on) if starts_on else date.today()
    except ValueError:
        return _redirect(program.id, error="Укажите корректную дату начала.")
    starts_at = datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)
    try:
        enrollment = enroll_student(db, program, student, starts_at)
    except ValueError as exc:
        return _redirect(program.id, error=str(exc))
    db.commit()
    return _redirect(
        program.id,
        notice=f"{student.name} зачислен(а); создано заданий: {len(enrollment.assignments)}.",
    )
