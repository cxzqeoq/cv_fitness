from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .crm_integration import enqueue_assignment_message
from sqlalchemy.orm import Session

from .models import (
    Assignment,
    AssignmentStatus,
    Enrollment,
    EnrollmentStatus,
    Lesson,
    LessonExercise,
    Program,
    ProgramStatus,
    Student,
)


def _is_available(available_at: datetime | None, moment: datetime) -> bool:
    if available_at is None:
        return True
    comparable_moment = moment
    if available_at.tzinfo is None and moment.tzinfo is not None:
        comparable_moment = moment.replace(tzinfo=None)
    return available_at <= comparable_moment

def _now(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def publish_program(program: Program, *, now: datetime | None = None) -> None:
    """Publish a complete draft and make its structure immutable."""
    if program.status != ProgramStatus.draft:
        raise ValueError("Опубликовать можно только черновик программы.")
    if not program.lessons:
        raise ValueError("Добавьте в программу хотя бы один урок.")
    if any(not lesson.exercises for lesson in program.lessons):
        raise ValueError("В каждом уроке должно быть хотя бы одно упражнение.")
    program.status = ProgramStatus.published
    program.published_at = _now(now)


def clone_program(db: Session, source: Program) -> Program:
    """Create an independent editable copy of a published program."""
    if source.status == ProgramStatus.draft:
        raise ValueError("Черновик уже можно редактировать без клонирования.")
    clone = Program(
        title=f"{source.title} — копия",
        description=source.description,
        status=ProgramStatus.draft,
    )
    for source_lesson in source.lessons:
        lesson = Lesson(
            position=source_lesson.position,
            title=source_lesson.title,
            content=source_lesson.content,
            unlock_offset_days=source_lesson.unlock_offset_days,
        )
        for source_item in source_lesson.exercises:
            lesson.exercises.append(
                LessonExercise(
                    exercise_id=source_item.exercise_id,
                    position=source_item.position,
                    instructions=source_item.instructions,
                    target_sets=source_item.target_sets,
                    target_reps=source_item.target_reps,
                    target_duration_sec=source_item.target_duration_sec,
                    reference_segment_id=source_item.reference_segment_id,
                    is_required=source_item.is_required,
                )
            )
        clone.lessons.append(lesson)
    db.add(clone)
    db.flush()
    return clone


def enroll_student(
    db: Session,
    program: Program,
    student: Student,
    starts_at: datetime,
    *,
    now: datetime | None = None,
) -> Enrollment:
    """Create one enrollment and materialize its immutable assignment plan."""
    if program.status != ProgramStatus.published:
        raise ValueError("Назначить можно только опубликованную программу.")
    if program.org_id != student.org_id:
        raise ValueError("Ученик и программа должны принадлежать одной организации.")
    enrollment = Enrollment(
        program_id=program.id,
        student_id=student.id,
        starts_at=starts_at,
        status=EnrollmentStatus.active,
    )
    db.add(enrollment)
    db.flush()

    for lesson in sorted(program.lessons, key=lambda item: (item.position, item.id)):
        available_at = starts_at + timedelta(days=lesson.unlock_offset_days)
        for item in sorted(lesson.exercises, key=lambda value: (value.position, value.id)):
            db.add(
                Assignment(
                    student_id=student.id,
                    exercise_id=item.exercise_id,
                    enrollment_id=enrollment.id,
                    lesson_exercise_id=item.id,
                    title=item.exercise.name,
                    available_at=available_at,
                    status=AssignmentStatus.locked,
                )
            )
    db.flush()
    refresh_enrollment(db, enrollment, now=now)
    return enrollment


def refresh_enrollment(
    db: Session,
    enrollment: Enrollment,
    *,
    now: datetime | None = None,
) -> None:
    """Open eligible lessons and derive completion from required assignments."""
    if enrollment.status in (EnrollmentStatus.paused, EnrollmentStatus.cancelled):
        return
    moment = _now(now)
    rows = (
        db.query(Assignment, LessonExercise, Lesson)
        .join(LessonExercise, LessonExercise.id == Assignment.lesson_exercise_id)
        .join(Lesson, Lesson.id == LessonExercise.lesson_id)
        .filter(Assignment.enrollment_id == enrollment.id)
        .order_by(Lesson.position, LessonExercise.position, Assignment.id)
        .all()
    )
    by_lesson: dict[int, list[tuple[Assignment, LessonExercise]]] = defaultdict(list)
    lesson_order: list[int] = []
    for assignment, item, lesson in rows:
        if lesson.id not in by_lesson:
            lesson_order.append(lesson.id)
        by_lesson[lesson.id].append((assignment, item))

    previous_required_complete = True
    for lesson_id in lesson_order:
        lesson_rows = by_lesson[lesson_id]
        date_open = all(
            _is_available(assignment.available_at, moment)
            for assignment, _item in lesson_rows
        )
        if previous_required_complete and date_open:
            for assignment, _item in lesson_rows:
                if assignment.status == AssignmentStatus.locked:
                    enqueue_assignment_message(db, assignment)
                    assignment.status = AssignmentStatus.assigned
        required = [assignment for assignment, item in lesson_rows if item.is_required]
        previous_required_complete = previous_required_complete and all(
            assignment.status == AssignmentStatus.completed for assignment in required
        )

    required_assignments = [
        assignment
        for assignment, item, _lesson in rows
        if item.is_required
    ]
    complete = bool(required_assignments) and all(
        assignment.status == AssignmentStatus.completed for assignment in required_assignments
    )
    if complete:
        enrollment.status = EnrollmentStatus.completed
        enrollment.completed_at = enrollment.completed_at or moment
    elif enrollment.status == EnrollmentStatus.completed:
        enrollment.status = EnrollmentStatus.active
        enrollment.completed_at = None
