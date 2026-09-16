from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, Text
from sqlalchemy.sql import func

from ..db import Base

DEFAULT_AI_PROMPT = (
    "Опиши коротко по-русски, что за упражнение делает человек на этом кадре "
    "и в какой он позе. 1-2 предложения, без вступлений."
)


class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, default=1)
    max_upload_bytes = Column(BigInteger, nullable=False, default=5 * 1024**3)
    target_sample_fps = Column(Integer, nullable=False, default=12)
    pose_model_complexity = Column(Integer, nullable=False, default=1)
    ai_prompt = Column(Text, nullable=False, default=DEFAULT_AI_PROMPT)
    show_skeleton = Column(Boolean, nullable=False, default=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
