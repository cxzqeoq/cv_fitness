import enum

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..db import Base


class AssignmentStatus(str, enum.Enum):
    assigned = "assigned"
    in_progress = "in_progress"
    submitted = "submitted"
    revision_requested = "revision_requested"
    completed = "completed"


class SubmissionStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    revision_requested = "revision_requested"
    accepted = "accepted"


class Assignment(Base):
    __tablename__ = "assignments"

    org_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    id = Column(Integer, primary_key=True)
    student_id = Column(
        Integer,
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    exercise_id = Column(
        Integer,
        ForeignKey("exercises.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    title = Column(String(200), nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=True, index=True)
    status = Column(
        Enum(AssignmentStatus, name="assignmentstatus"),
        nullable=False,
        default=AssignmentStatus.assigned,
        index=True,
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    submissions = relationship(
        "Submission",
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="Submission.attempt",
    )


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("assignment_id", "attempt", name="uq_submissions_assignment_attempt"),
        Index(
            "uq_submissions_one_accepted",
            "assignment_id",
            unique=True,
            postgresql_where=text("status = 'accepted'"),
            sqlite_where=text("status = 'accepted'"),
        ),
    )

    id = Column(Integer, primary_key=True)
    assignment_id = Column(
        Integer,
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_id = Column(
        Integer,
        ForeignKey("videos.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    attempt = Column(Integer, nullable=False)
    status = Column(
        Enum(SubmissionStatus, name="submissionstatus"),
        nullable=False,
        default=SubmissionStatus.draft,
        index=True,
    )
    student_comment = Column(Text, nullable=True)
    coach_comment = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    assignment = relationship("Assignment", back_populates="submissions")
    video = relationship("Video")
