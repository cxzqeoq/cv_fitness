from datetime import datetime, timezone

from .models import AssignmentStatus, StudentVideo


STUDENT_COMMENT_LIMIT = 2000
COACH_COMMENT_LIMIT = 3000


def start_assignment(assignment: StudentVideo, *, now: datetime | None = None) -> None:
    """Move a new assignment into active work without regressing later states."""
    if assignment.status == AssignmentStatus.completed:
        raise ValueError("Завершённую тренировку нельзя начать заново без решения тренера.")
    if assignment.status == AssignmentStatus.submitted:
        raise ValueError("Тренировка уже отправлена тренеру.")
    if assignment.status == AssignmentStatus.assigned:
        assignment.status = AssignmentStatus.in_progress
        assignment.started_at = now or datetime.now(timezone.utc)


def submit_assignment(
    assignment: StudentVideo,
    student_comment: str,
    *,
    now: datetime | None = None,
) -> None:
    """Submit student feedback and move the assignment to trainer review."""
    if assignment.status == AssignmentStatus.completed:
        raise ValueError("Завершённую тренировку нельзя изменить без решения тренера.")
    clean_comment = student_comment.strip()
    if len(clean_comment) > STUDENT_COMMENT_LIMIT:
        raise ValueError(f"Комментарий должен быть короче {STUDENT_COMMENT_LIMIT} символов.")
    moment = now or datetime.now(timezone.utc)
    assignment.started_at = assignment.started_at or moment
    assignment.student_comment = clean_comment or None
    assignment.status = AssignmentStatus.submitted
    assignment.submitted_at = moment


def review_assignment(
    assignment: StudentVideo,
    action: str,
    coach_comment: str,
    *,
    now: datetime | None = None,
) -> None:
    """Save trainer feedback and apply an allowed review transition."""
    clean_comment = coach_comment.strip()
    if len(clean_comment) > COACH_COMMENT_LIMIT:
        raise ValueError(f"Комментарий тренера должен быть короче {COACH_COMMENT_LIMIT} символов.")
    assignment.coach_comment = clean_comment or None
    moment = now or datetime.now(timezone.utc)
    if action == "save":
        return
    if action == "complete":
        if assignment.status not in (AssignmentStatus.submitted, AssignmentStatus.completed):
            raise ValueError("Завершить можно только тренировку, отправленную учеником.")
        assignment.status = AssignmentStatus.completed
        assignment.completed_at = assignment.completed_at or moment
        return
    if action == "reopen":
        if assignment.status not in (AssignmentStatus.submitted, AssignmentStatus.completed):
            raise ValueError("Вернуть в работу можно только отправленную или завершённую тренировку.")
        assignment.status = AssignmentStatus.in_progress
        assignment.completed_at = None
        return
    raise ValueError("Неизвестное действие с тренировкой.")


def reset_assignment(assignment: StudentVideo) -> None:
    """Reset workflow data when a video is transferred to another student."""
    assignment.status = AssignmentStatus.assigned
    assignment.student_comment = None
    assignment.coach_comment = None
    assignment.started_at = None
    assignment.submitted_at = None
    assignment.completed_at = None
