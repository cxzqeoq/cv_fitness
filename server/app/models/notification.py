import enum

from sqlalchemy import Column, DateTime, Enum, Index, Integer, String, Text, Uuid
from sqlalchemy.sql import func

from ..db import Base


class NotificationRecipient(str, enum.Enum):
    staff = "staff"
    student = "student"


class NotificationEvent(str, enum.Enum):
    assignment_created = "assignment_created"
    assignment_submitted = "assignment_submitted"
    trainer_replied = "trainer_replied"
    assignment_completed = "assignment_completed"
    assignment_reopened = "assignment_reopened"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "ix_notifications_org_recipient_unread",
            "org_id",
            "recipient_kind",
            "recipient_id",
            "read_at",
        ),
    )

    org_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    id = Column(Integer, primary_key=True)
    recipient_kind = Column(Enum(NotificationRecipient), nullable=False)
    recipient_id = Column(Integer, nullable=False)
    event = Column(Enum(NotificationEvent), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    url = Column(String(500), nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
