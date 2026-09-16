from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..auth import csrf_token
from ..config import BASE_DIR
from ..db import get_db
from ..models import Notification, NotificationRecipient
from ..notification_service import mark_all_read


router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _notifications(
    db: Session,
    *,
    recipient_kind: NotificationRecipient,
    recipient_id: int,
) -> list[Notification]:
    return (
        db.query(Notification)
        .filter(
            Notification.recipient_kind == recipient_kind,
            Notification.recipient_id == recipient_id,
        )
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(100)
        .all()
    )


@router.get("/notifications")
def staff_notifications(request: Request, db: Session = Depends(get_db)) -> Response:
    principal = request.state.principal
    return templates.TemplateResponse(
        "admin/notifications.html",
        {
            "request": request,
            "active": "notifications",
            "notifications": _notifications(
                db,
                recipient_kind=NotificationRecipient.staff,
                recipient_id=principal["id"],
            ),
        },
    )


@router.post("/notifications/read-all")
def staff_notifications_read_all(
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    principal = request.state.principal
    mark_all_read(
        db,
        recipient_kind=NotificationRecipient.staff,
        recipient_id=principal["id"],
    )
    db.commit()
    return RedirectResponse("/notifications", status_code=303)


@router.get("/student/notifications")
def student_notifications(request: Request, db: Session = Depends(get_db)) -> Response:
    principal = request.state.principal
    return templates.TemplateResponse(
        "student/notifications.html",
        {
            "request": request,
            "principal": principal,
            "notifications": _notifications(
                db,
                recipient_kind=NotificationRecipient.student,
                recipient_id=principal["student_id"],
            ),
            "csrf_token": csrf_token(request),
        },
    )


@router.post("/student/notifications/read-all")
def student_notifications_read_all(
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    principal = request.state.principal
    mark_all_read(
        db,
        recipient_kind=NotificationRecipient.student,
        recipient_id=principal["student_id"],
    )
    db.commit()
    return RedirectResponse("/student/notifications", status_code=303)
