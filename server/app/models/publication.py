from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from ..db import Base


class VideoPublication(Base):
    __tablename__ = "video_publications"

    video_id = Column(
        Integer,
        ForeignKey("videos.id", ondelete="CASCADE"),
        primary_key=True,
    )
    token = Column(String(64), nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
