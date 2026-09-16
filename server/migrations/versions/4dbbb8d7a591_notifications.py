"""notifications

Revision ID: 4dbbb8d7a591
Revises: 1c8c3e7702f1
Create Date: 2026-09-16 17:15:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "4dbbb8d7a591"
down_revision: Union[str, None] = "1c8c3e7702f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "recipient_kind",
            sa.Enum("staff", "student", name="notificationrecipient"),
            nullable=False,
        ),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column(
            "event",
            sa.Enum(
                "assignment_created",
                "assignment_submitted",
                "trainer_replied",
                "assignment_completed",
                "assignment_reopened",
                name="notificationevent",
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_recipient_unread",
        "notifications",
        ["recipient_kind", "recipient_id", "read_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_recipient_unread", table_name="notifications")
    op.drop_table("notifications")
    sa.Enum(name="notificationevent").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="notificationrecipient").drop(op.get_bind(), checkfirst=True)
