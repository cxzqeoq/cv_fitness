import enum

from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.sql import func

from ..db import Base


class StudentStatus(str, enum.Enum):
    active = "active"
    archived = "archived"


class AssignmentStatus(str, enum.Enum):
    assigned = "assigned"
    in_progress = "in_progress"
    submitted = "submitted"
    completed = "completed"


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_students_org_email"),
        UniqueConstraint("org_id", "oidc_sub", name="uq_students_org_oidc_sub"),
    )

    org_id = Column(Uuid(as_uuid=True), nullable=False, index=True)

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, index=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(320), nullable=True)
    birth_date = Column(Date, nullable=True)
    oidc_sub = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(Enum(StudentStatus), nullable=False, default=StudentStatus.active, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class StudentVideo(Base):
    __tablename__ = "student_videos"

    video_id = Column(
        Integer,
        ForeignKey("videos.id", ondelete="CASCADE"),
        primary_key=True,
    )
    student_id = Column(
        Integer,
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    exercise_name = Column(String(200), nullable=True)
    training_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status = Column(
        Enum(AssignmentStatus),
        nullable=False,
        default=AssignmentStatus.assigned,
        index=True,
    )
    student_comment = Column(Text, nullable=True)
    coach_comment = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
