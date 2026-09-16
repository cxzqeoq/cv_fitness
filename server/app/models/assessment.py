import enum

from sqlalchemy import CheckConstraint, Column, DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.sql import func

from ..db import Base


class AssessmentStatus(str, enum.Enum):
    draft = "draft"
    final = "final"


def _score_constraints() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("technique IS NULL OR technique BETWEEN 1 AND 5"),
        CheckConstraint("range_of_motion IS NULL OR range_of_motion BETWEEN 1 AND 5"),
        CheckConstraint("stability IS NULL OR stability BETWEEN 1 AND 5"),
        CheckConstraint("tempo IS NULL OR tempo BETWEEN 1 AND 5"),
        CheckConstraint("symmetry IS NULL OR symmetry BETWEEN 1 AND 5"),
    )


class VideoAssessment(Base):
    __tablename__ = "video_assessments"
    __table_args__ = _score_constraints()

    video_id = Column(
        Integer,
        ForeignKey("videos.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status = Column(Enum(AssessmentStatus), nullable=False, default=AssessmentStatus.draft)
    technique = Column(Integer, nullable=True)
    range_of_motion = Column(Integer, nullable=True)
    stability = Column(Integer, nullable=True)
    tempo = Column(Integer, nullable=True)
    symmetry = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)
    recommendations = Column(Text, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SegmentAssessment(Base):
    __tablename__ = "segment_assessments"
    __table_args__ = _score_constraints()

    segment_id = Column(
        Integer,
        ForeignKey("segments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    technique = Column(Integer, nullable=True)
    range_of_motion = Column(Integer, nullable=True)
    stability = Column(Integer, nullable=True)
    tempo = Column(Integer, nullable=True)
    symmetry = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
