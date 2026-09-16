import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.sql import func

from ..db import Base


class TeamRole(str, enum.Enum):
    owner = "owner"
    manager = "manager"
    editor = "editor"


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_team_members_org_email"),
        UniqueConstraint("org_id", "oidc_sub", name="uq_team_members_org_oidc_sub"),
    )

    org_id = Column(Uuid(as_uuid=True), nullable=False, index=True)

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(320), nullable=False, index=True)
    oidc_sub = Column(String(200), nullable=True)
    role = Column(Enum(TeamRole, name="team_role"), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
