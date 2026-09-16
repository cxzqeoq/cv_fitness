import re
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..db import get_db
from ..models import AuditEvent, Student, StudentAccount, TeamMember, TeamRole

router = APIRouter(prefix="/team")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ROLE_LABELS = {
    TeamRole.owner: "Владелец",
    TeamRole.manager: "Управляющий",
    TeamRole.editor: "Редактор",
}


def _redirect(
    *,
    error: str | None = None,
    notice: str | None = None,
    member_id: int | None = None,
) -> RedirectResponse:
    params = {}
    if error:
        params["error"] = error
    if notice:
        params["notice"] = notice
    url = "/team"
    if params:
        url = f"{url}?{urlencode(params)}"
    if member_id is not None:
        url = f"{url}#member-{member_id}"
    return RedirectResponse(url=url, status_code=303)


def _validated_fields(name: str, email: str, role: str) -> tuple[str, str, TeamRole] | str:
    clean_name = name.strip()
    clean_email = email.strip().lower()
    if not clean_name or len(clean_name) > 100:
        return "Имя обязательно и должно быть короче 100 символов."
    if len(clean_email) > 320 or not _EMAIL_RE.fullmatch(clean_email):
        return "Укажите корректный email."
    try:
        clean_role = TeamRole(role)
    except ValueError:
        return "Выберите допустимую роль."
    return clean_name, clean_email, clean_role


def _active_owner_count(db: Session) -> int:
    return (
        db.query(TeamMember)
        .filter(
            TeamMember.role == TeamRole.owner,
            TeamMember.is_active.is_(True),
        )
        .count()
    )


@router.get("")
def team_list(
    request: Request,
    error: str = "",
    notice: str = "",
    db: Session = Depends(get_db),
) -> Response:
    members = (
        db.query(TeamMember)
        .order_by(TeamMember.is_active.desc(), TeamMember.name, TeamMember.id)
        .all()
    )
    audit_events = db.query(AuditEvent).order_by(AuditEvent.id.desc()).limit(50).all()
    actor_labels = {}
    for event in audit_events:
        if event.actor_kind == "staff":
            member = db.get(TeamMember, int(event.actor_id))
            actor_labels[event.id] = member.name if member is not None else f"Сотрудник #{event.actor_id}"
        elif event.actor_kind == "student":
            account = db.get(StudentAccount, int(event.actor_id))
            student = db.get(Student, account.student_id) if account is not None else None
            actor_labels[event.id] = student.name if student is not None else f"Ученик #{event.actor_id}"
        else:
            actor_labels[event.id] = event.actor_kind
    return templates.TemplateResponse(
        "admin/team.html",
        {
            "request": request,
            "active": "team",
            "members": members,
            "active_count": sum(member.is_active for member in members),
            "active_owner_count": _active_owner_count(db),
            "role_labels": _ROLE_LABELS,
            "roles": list(TeamRole),
            "audit_events": audit_events,
            "actor_labels": actor_labels,
            "error": error[:500],
            "notice": notice[:500],
        },
    )


@router.post("")
def create_member(
    name: str = Form(""),
    email: str = Form(""),
    role: str = Form("owner"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    validated = _validated_fields(name, email, role)
    if isinstance(validated, str):
        return _redirect(error=validated)
    clean_name, clean_email, clean_role = validated
    if db.query(TeamMember).filter(TeamMember.email == clean_email).first() is not None:
        return _redirect(error="Участник с таким email уже существует.")
    if db.query(TeamMember).count() == 0 and clean_role != TeamRole.owner:
        return _redirect(error="Первый участник команды должен быть владельцем.")

    member = TeamMember(
        name=clean_name,
        email=clean_email,
        role=clean_role,
        is_active=True,
    )
    try:
        db.add(member)
        db.commit()
        db.refresh(member)
    except IntegrityError:
        db.rollback()
        return _redirect(error="Участник с таким email уже существует.")
    return _redirect(notice="Участник добавлен.", member_id=member.id)


@router.post("/{member_id}")
def update_member(
    member_id: int,
    name: str = Form(""),
    email: str = Form(""),
    role: str = Form("manager"),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    member = db.get(TeamMember, member_id)
    if member is None:
        raise HTTPException(404, "team member not found")
    validated = _validated_fields(name, email, role)
    if isinstance(validated, str):
        return _redirect(error=validated, member_id=member_id)
    clean_name, clean_email, clean_role = validated
    active = is_active == "on"

    duplicate = (
        db.query(TeamMember)
        .filter(TeamMember.email == clean_email, TeamMember.id != member_id)
        .first()
    )
    if duplicate is not None:
        return _redirect(error="Участник с таким email уже существует.", member_id=member_id)
    if (
        member.role == TeamRole.owner
        and member.is_active
        and (clean_role != TeamRole.owner or not active)
        and _active_owner_count(db) <= 1
    ):
        return _redirect(
            error="Нельзя отключить или понизить последнего активного владельца.",
            member_id=member_id,
        )

    member.name = clean_name
    member.email = clean_email
    member.role = clean_role
    member.is_active = active
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _redirect(error="Участник с таким email уже существует.", member_id=member_id)
    return _redirect(notice="Изменения сохранены.", member_id=member_id)


@router.post("/{member_id}/delete")
def delete_member(member_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    member = db.get(TeamMember, member_id)
    if member is None:
        raise HTTPException(404, "team member not found")
    if (
        member.role == TeamRole.owner
        and member.is_active
        and _active_owner_count(db) <= 1
    ):
        return _redirect(
            error="Нельзя удалить последнего активного владельца.",
            member_id=member_id,
        )
    db.delete(member)
    db.commit()
    return _redirect(notice="Участник удалён.")
