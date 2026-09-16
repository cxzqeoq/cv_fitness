import enum

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.sql import func

from ..db import Base


class CrmInboxStatus(str, enum.Enum):
    processed = "processed"
    ignored = "ignored"


class CrmOutboxStatus(str, enum.Enum):
    pending = "pending"
    delivered = "delivered"


class CrmOrganizationBinding(Base):
    __tablename__ = "crm_organization_bindings"
    __table_args__ = (
        UniqueConstraint("org_id", name="uq_crm_bindings_org"),
        UniqueConstraint("crm_company_id", name="uq_crm_bindings_company"),
    )

    id = Column(Integer, primary_key=True)
    org_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    crm_company_id = Column(Integer, nullable=False, index=True)
    api_key = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CrmInboundEvent(Base):
    __tablename__ = "crm_inbound_events"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "source_event_key",
            name="uq_crm_inbound_org_event",
        ),
    )

    id = Column(Integer, primary_key=True)
    org_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    source_event_key = Column(String(200), nullable=False)
    event_type = Column(String(80), nullable=False)
    crm_lead_id = Column(Integer, nullable=True, index=True)
    payload = Column(JSON, nullable=False)
    status = Column(
        Enum(CrmInboxStatus, name="crminboxstatus"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CrmOutboxEvent(Base):
    __tablename__ = "crm_outbox_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_crm_outbox_idempotency"),
    )

    id = Column(Integer, primary_key=True)
    org_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    student_id = Column(
        Integer,
        ForeignKey("students.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    crm_lead_id = Column(Integer, nullable=False, index=True)
    event_type = Column(String(80), nullable=False)
    idempotency_key = Column(String(200), nullable=False)
    text = Column(Text, nullable=False)
    status = Column(
        Enum(CrmOutboxStatus, name="crmoutboxstatus"),
        nullable=False,
        default=CrmOutboxStatus.pending,
        index=True,
    )
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
