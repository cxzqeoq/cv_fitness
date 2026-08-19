import enum

from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..db import Base


class VideoStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True)
    filename = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    status = Column(Enum(VideoStatus), default=VideoStatus.pending, nullable=False)
    error = Column(Text, nullable=True)
    duration_sec = Column(Float, nullable=True)
    fps = Column(Float, nullable=True)
    track_path = Column(String, nullable=True)  # skeleton JSON track, relative to storage
    frames_total = Column(Integer, nullable=True)
    frames_done = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    segments = relationship(
        "Segment", back_populates="video", cascade="all, delete-orphan",
        order_by="Segment.start_sec",
    )


class Segment(Base):
    __tablename__ = "segments"

    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    start_sec = Column(Float, nullable=False)
    end_sec = Column(Float, nullable=False)
    label = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    subtitle = Column(Text, nullable=True)

    video = relationship("Video", back_populates="segments")
