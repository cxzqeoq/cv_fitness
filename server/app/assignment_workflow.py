from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import (
    Assignment,
    AssignmentStatus,
    Submission,
    SubmissionStatus,
)


STUDENT_COMMENT_LIMIT = 2000
COACH_COMMENT_LIMIT = 3000


def submission_for_video(db: Session, video_id: int) -> Submission | None:
    return (
        db.query(Submission)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .filter(Submission.video_id == video_id)
        .first()
    )


def latest_submission(db: Session, assignment_id: int) -> Submission | None:
    return (
        db.query(Submission)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .filter(Submission.assignment_id == assignment_id)
        .order_by(Submission.attempt.desc())
        .first()
    )


def next_attempt(db: Session, assignment_id: int) -> int:
    latest = latest_submission(db, assignment_id)
    return 1 if latest is None else latest.attempt + 1


def start_assignment(assignment: Assignment, *, now: datetime | None = None) -> None:
    """Move an assigned or returned workout into active work."""
    if assignment.status == AssignmentStatus.completed:
        raise ValueError("Завершённую тренировку нельзя начать заново без решения тренера.")
    if assignment.status == AssignmentStatus.submitted:
        raise ValueError("Тренировка уже отправлена тренеру.")
    if assignment.status in (
        AssignmentStatus.assigned,
        AssignmentStatus.revision_requested,
    ):
        assignment.status = AssignmentStatus.in_progress
        assignment.started_at = assignment.started_at or now or datetime.now(timezone.utc)


def submit_assignment(
    assignment: Assignment,
    submission: Submission,
    student_comment: str,
    *,
    now: datetime | None = None,
) -> None:
    """Submit one immutable attempt to trainer review."""
    if assignment.status == AssignmentStatus.completed:
        raise ValueError("Завершённую тренировку нельзя изменить без решения тренера.")
    if submission.status != SubmissionStatus.draft:
        raise ValueError("Эта попытка уже отправлена тренеру.")
    clean_comment = student_comment.strip()
    if len(clean_comment) > STUDENT_COMMENT_LIMIT:
        raise ValueError(f"Комментарий должен быть короче {STUDENT_COMMENT_LIMIT} символов.")
    moment = now or datetime.now(timezone.utc)
    assignment.started_at = assignment.started_at or moment
    assignment.status = AssignmentStatus.submitted
    submission.student_comment = clean_comment or None
    submission.status = SubmissionStatus.submitted
    submission.submitted_at = moment


def review_submission(
    assignment: Assignment,
    submission: Submission,
    action: str,
    coach_comment: str,
    *,
    now: datetime | None = None,
) -> None:
    """Save trainer feedback and apply an allowed review transition."""
    clean_comment = coach_comment.strip()
    if len(clean_comment) > COACH_COMMENT_LIMIT:
        raise ValueError(f"Комментарий тренера должен быть короче {COACH_COMMENT_LIMIT} символов.")
    if action == "save":
        submission.coach_comment = clean_comment or None
        return

    moment = now or datetime.now(timezone.utc)
    if action == "complete":
        if submission.status not in (
            SubmissionStatus.submitted,
            SubmissionStatus.accepted,
        ):
            raise ValueError("Принять можно только попытку, отправленную учеником.")
        submission.coach_comment = clean_comment or None
        submission.status = SubmissionStatus.accepted
        submission.reviewed_at = submission.reviewed_at or moment
        assignment.status = AssignmentStatus.completed
        assignment.completed_at = assignment.completed_at or moment
        return
    if action == "reopen":
        if submission.status not in (
            SubmissionStatus.submitted,
            SubmissionStatus.accepted,
        ):
            raise ValueError("Вернуть можно только отправленную или принятую попытку.")
        submission.coach_comment = clean_comment or None
        submission.status = SubmissionStatus.revision_requested
        submission.reviewed_at = moment
        assignment.status = AssignmentStatus.revision_requested
        assignment.completed_at = None
        return
    raise ValueError("Неизвестное действие с тренировкой.")
