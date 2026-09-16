import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..db import Base


class ProgramStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


class EnrollmentStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"


class Program(Base):
    __tablename__ = "programs"

    org_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    status = Column(
        Enum(ProgramStatus, name="programstatus"),
        nullable=False,
        default=ProgramStatus.draft,
        index=True,
    )
    published_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    lessons = relationship(
        "Lesson",
        back_populates="program",
        cascade="all, delete-orphan",
        order_by="Lesson.position",
    )
    enrollments = relationship("Enrollment", back_populates="program")


class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (
        UniqueConstraint("program_id", "position", name="uq_lessons_program_position"),
    )

    id = Column(Integer, primary_key=True)
    program_id = Column(
        Integer,
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=True)
    unlock_offset_days = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    program = relationship("Program", back_populates="lessons")
    exercises = relationship(
        "LessonExercise",
        back_populates="lesson",
        cascade="all, delete-orphan",
        order_by="LessonExercise.position",
    )


class LessonExercise(Base):
    __tablename__ = "lesson_exercises"
    __table_args__ = (
        UniqueConstraint("lesson_id", "position", name="uq_lesson_exercises_lesson_position"),
    )

    id = Column(Integer, primary_key=True)
    lesson_id = Column(
        Integer,
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exercise_id = Column(
        Integer,
        ForeignKey("exercises.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    position = Column(Integer, nullable=False)
    instructions = Column(Text, nullable=True)
    target_sets = Column(Integer, nullable=True)
    target_reps = Column(Integer, nullable=True)
    target_duration_sec = Column(Integer, nullable=True)
    reference_segment_id = Column(
        Integer,
        ForeignKey("segments.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_required = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    lesson = relationship("Lesson", back_populates="exercises")
    exercise = relationship("Exercise")


class Enrollment(Base):
    __tablename__ = "enrollments"

    org_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    id = Column(Integer, primary_key=True)
    program_id = Column(
        Integer,
        ForeignKey("programs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    student_id = Column(
        Integer,
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    starts_at = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(
        Enum(EnrollmentStatus, name="enrollmentstatus"),
        nullable=False,
        default=EnrollmentStatus.active,
        index=True,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    program = relationship("Program", back_populates="enrollments")
    student = relationship("Student")
    assignments = relationship(
        "Assignment",
        back_populates="enrollment",
        order_by="Assignment.available_at, Assignment.id",
    )
