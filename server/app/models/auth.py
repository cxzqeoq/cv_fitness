from sqlalchemy import Column, DateTime, Integer, JSON, String, Uuid
from sqlalchemy.sql import func

from ..db import Base




class AuditEvent(Base):
    __tablename__ = "audit_events"

    org_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    id = Column(Integer, primary_key=True)
    actor_kind = Column(String(20), nullable=False, index=True)
    actor_id = Column(String(200), nullable=False, index=True)
    action = Column(String(20), nullable=False)
    path = Column(String(500), nullable=False)
    status_code = Column(Integer, nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
