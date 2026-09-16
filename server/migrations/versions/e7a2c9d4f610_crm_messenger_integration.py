"""crm_messenger_integration

Revision ID: e7a2c9d4f610
Revises: d5f1b8a207c4
Create Date: 2026-09-16 19:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "e7a2c9d4f610"
down_revision: Union[str, None] = "d5f1b8a207c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inbox_status = postgresql.ENUM(
        "processed",
        "ignored",
        name="crminboxstatus",
        create_type=False,
    )
    outbox_status = postgresql.ENUM(
        "pending",
        "delivered",
        name="crmoutboxstatus",
        create_type=False,
    )
    inbox_status.create(op.get_bind(), checkfirst=True)
    outbox_status.create(op.get_bind(), checkfirst=True)

    op.add_column("students", sa.Column("crm_lead_id", sa.Integer(), nullable=True))
    op.create_unique_constraint(
        "uq_students_org_crm_lead",
        "students",
        ["org_id", "crm_lead_id"],
    )

    op.create_table(
        "crm_organization_bindings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crm_company_id", sa.Integer(), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crm_company_id", name="uq_crm_bindings_company"),
        sa.UniqueConstraint("org_id", name="uq_crm_bindings_org"),
    )
    op.create_index(
        "ix_crm_organization_bindings_org_id",
        "crm_organization_bindings",
        ["org_id"],
        unique=False,
    )
    op.create_index(
        "ix_crm_organization_bindings_crm_company_id",
        "crm_organization_bindings",
        ["crm_company_id"],
        unique=False,
    )

    op.create_table(
        "crm_inbound_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_event_key", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("crm_lead_id", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", inbox_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "source_event_key", name="uq_crm_inbound_org_event"),
    )
    op.create_index("ix_crm_inbound_events_org_id", "crm_inbound_events", ["org_id"], unique=False)
    op.create_index("ix_crm_inbound_events_crm_lead_id", "crm_inbound_events", ["crm_lead_id"], unique=False)

    op.create_table(
        "crm_outbox_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=True),
        sa.Column("crm_lead_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", outbox_status, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_crm_outbox_idempotency"),
    )
    op.create_index("ix_crm_outbox_events_org_id", "crm_outbox_events", ["org_id"], unique=False)
    op.create_index("ix_crm_outbox_events_student_id", "crm_outbox_events", ["student_id"], unique=False)
    op.create_index("ix_crm_outbox_events_crm_lead_id", "crm_outbox_events", ["crm_lead_id"], unique=False)
    op.create_index("ix_crm_outbox_events_status", "crm_outbox_events", ["status"], unique=False)
    op.create_index("ix_crm_outbox_events_next_attempt_at", "crm_outbox_events", ["next_attempt_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_crm_outbox_events_next_attempt_at", table_name="crm_outbox_events")
    op.drop_index("ix_crm_outbox_events_status", table_name="crm_outbox_events")
    op.drop_index("ix_crm_outbox_events_crm_lead_id", table_name="crm_outbox_events")
    op.drop_index("ix_crm_outbox_events_student_id", table_name="crm_outbox_events")
    op.drop_index("ix_crm_outbox_events_org_id", table_name="crm_outbox_events")
    op.drop_table("crm_outbox_events")
    op.drop_index("ix_crm_inbound_events_crm_lead_id", table_name="crm_inbound_events")
    op.drop_index("ix_crm_inbound_events_org_id", table_name="crm_inbound_events")
    op.drop_table("crm_inbound_events")
    op.drop_index("ix_crm_organization_bindings_crm_company_id", table_name="crm_organization_bindings")
    op.drop_index("ix_crm_organization_bindings_org_id", table_name="crm_organization_bindings")
    op.drop_table("crm_organization_bindings")
    op.drop_constraint("uq_students_org_crm_lead", "students", type_="unique")
    op.drop_column("students", "crm_lead_id")
    postgresql.ENUM(name="crmoutboxstatus").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="crminboxstatus").drop(op.get_bind(), checkfirst=True)
