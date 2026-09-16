from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func

from ..db import Base


class StudentAccount(Base):
    __tablename__ = "student_accounts"

    id = Column(Integer, primary_key=True)
    student_id = Column(
        Integer,
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    email = Column(String(320), nullable=False, unique=True, index=True)
    password_hash = Column(String(512), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)


class StaffIdentity(Base):
    __tablename__ = "staff_identities"

    team_member_id = Column(
        Integer,
        ForeignKey("team_members.id", ondelete="CASCADE"),
        primary_key=True,
    )
    oidc_sub = Column(String(200), nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    actor_kind = Column(String(20), nullable=False, index=True)
    actor_id = Column(String(200), nullable=False, index=True)
    action = Column(String(20), nullable=False)
    path = Column(String(500), nullable=False)
    status_code = Column(Integer, nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
