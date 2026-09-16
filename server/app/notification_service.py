from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import (
    Notification,
    NotificationEvent,
    NotificationRecipient,
    TeamMember,
    TeamRole,
)


def notify_student(
    db: Session,
    *,
    student_id: int,
    event: NotificationEvent,
    title: str,
    body: str,
    url: str,
) -> None:
    db.add(
        Notification(
            recipient_kind=NotificationRecipient.student,
            recipient_id=student_id,
            event=event,
            title=title,
            body=body,
            url=url,
        )
    )


def notify_reviewers(
    db: Session,
    *,
    event: NotificationEvent,
    title: str,
    body: str,
    url: str,
) -> int:
    reviewers = (
        db.query(TeamMember)
        .filter(
            TeamMember.is_active.is_(True),
            TeamMember.role.in_((TeamRole.owner, TeamRole.manager)),
        )
        .all()
    )
    for member in reviewers:
        db.add(
            Notification(
                recipient_kind=NotificationRecipient.staff,
                recipient_id=member.id,
                event=event,
                title=title,
                body=body,
                url=url,
            )
        )
    return len(reviewers)


def unread_count(
    db: Session,
    *,
    recipient_kind: NotificationRecipient,
    recipient_id: int,
) -> int:
    return (
        db.query(Notification)
        .filter(
            Notification.recipient_kind == recipient_kind,
            Notification.recipient_id == recipient_id,
            Notification.read_at.is_(None),
        )
        .count()
    )


def mark_all_read(
    db: Session,
    *,
    recipient_kind: NotificationRecipient,
    recipient_id: int,
) -> int:
    return (
        db.query(Notification)
        .filter(
            Notification.recipient_kind == recipient_kind,
            Notification.recipient_id == recipient_id,
            Notification.read_at.is_(None),
        )
        .update({Notification.read_at: datetime.now(timezone.utc)}, synchronize_session=False)
    )
