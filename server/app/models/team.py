import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String
from sqlalchemy.sql import func

from ..db import Base


class TeamRole(str, enum.Enum):
    owner = "owner"
    manager = "manager"
    editor = "editor"


class TeamMember(Base):
    __tablename__ = "team_members"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(320), nullable=False, unique=True, index=True)
    role = Column(Enum(TeamRole, name="team_role"), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
