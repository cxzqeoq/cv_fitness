import enum

from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.sql import func

from ..db import Base


class ExerciseStatus(str, enum.Enum):
    active = "active"
    archived = "archived"


class Exercise(Base):
    __tablename__ = "exercises"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_exercises_org_name"),)

    org_id = Column(Uuid(as_uuid=True), nullable=False, index=True)

    angle_tolerance = Column(Integer, nullable=False, default=15)
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    instructions = Column(Text, nullable=True)
    status = Column(Enum(ExerciseStatus), nullable=False, default=ExerciseStatus.active, index=True)
    reference_segment_id = Column(
        Integer,
        ForeignKey("segments.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SegmentExercise(Base):
    __tablename__ = "segment_exercises"

    segment_id = Column(
        Integer,
        ForeignKey("segments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    exercise_id = Column(
        Integer,
        ForeignKey("exercises.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class SegmentComparison(Base):
    __tablename__ = "segment_comparisons"

    segment_id = Column(
        Integer,
        ForeignKey("segments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    exercise_id = Column(
        Integer,
        ForeignKey("exercises.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reference_segment_id = Column(
        Integer,
        ForeignKey("segments.id", ondelete="CASCADE"),
        nullable=False,
    )
    tempo_score = Column(Float, nullable=False)
    score = Column(Float, nullable=False)
    feature_scores = Column(JSON, nullable=False)
    sample_count = Column(Integer, nullable=False)
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
