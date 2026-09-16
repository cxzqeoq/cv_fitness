import enum

from sqlalchemy import Column, Date, DateTime, Enum, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.sql import func

from ..db import Base


class StudentStatus(str, enum.Enum):
    active = "active"
    archived = "archived"




class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_students_org_email"),
        UniqueConstraint("org_id", "oidc_sub", name="uq_students_org_oidc_sub"),
    )

    org_id = Column(Uuid(as_uuid=True), nullable=False, index=True)

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, index=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(320), nullable=True)
    birth_date = Column(Date, nullable=True)
    oidc_sub = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(Enum(StudentStatus), nullable=False, default=StudentStatus.active, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


