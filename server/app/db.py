import uuid

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker, with_loader_criteria

from .config import DATABASE_URL


class TenantSession(Session):
    pass


engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=TenantSession,
)
Base = declarative_base()


def _tenant_models() -> tuple[type, ...]:
    from .models import (
        AppSettings,
        Assignment,
        AuditEvent,
        Exercise,
        Enrollment,
        Notification,
        Student,
        Program,
        TeamMember,
        Video,
    )

    return (
        AppSettings,
        Assignment,
        AuditEvent,
        Enrollment,
        Exercise,
        Notification,
        Program,
        Student,
        TeamMember,
        Video,
    )


def set_tenant(db: Session, org_id: uuid.UUID | str) -> uuid.UUID:
    parsed = org_id if isinstance(org_id, uuid.UUID) else uuid.UUID(str(org_id))
    db.info["org_id"] = parsed
    return parsed


@event.listens_for(TenantSession, "do_orm_execute")
def _scope_tenant_reads(execute_state) -> None:
    org_id = execute_state.session.info.get("org_id")
    if org_id is None or not execute_state.is_select:
        return
    statement = execute_state.statement
    for model in _tenant_models():
        statement = statement.options(
            with_loader_criteria(
                model,
                lambda cls: cls.org_id == org_id,
                include_aliases=True,
            )
        )
    execute_state.statement = statement


@event.listens_for(TenantSession, "before_flush")
def _scope_tenant_writes(session: TenantSession, _flush_context, _instances) -> None:
    org_id = session.info.get("org_id")
    if org_id is None:
        return
    tenant_models = _tenant_models()
    for value in session.new:
        if not isinstance(value, tenant_models):
            continue
        current = getattr(value, "org_id", None)
        if current is None:
            value.org_id = org_id
        elif current != org_id:
            raise ValueError("cross-tenant insert rejected")


def get_db(request: Request):
    db = SessionLocal()
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        set_tenant(db, principal["org_id"])
    try:
        yield db
    finally:
        db.close()
