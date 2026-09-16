"""assignment workflow

Revision ID: 1c8c3e7702f1
Revises: 788d5ad60bc4
Create Date: 2026-09-16 16:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "1c8c3e7702f1"
down_revision: Union[str, None] = "788d5ad60bc4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


assignment_status = postgresql.ENUM(
    "assigned",
    "in_progress",
    "submitted",
    "completed",
    name="assignmentstatus",
)


def upgrade() -> None:
    assignment_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "student_videos",
        sa.Column(
            "status",
            assignment_status,
            nullable=False,
            server_default=sa.text("'assigned'"),
        ),
    )
    op.add_column("student_videos", sa.Column("student_comment", sa.Text(), nullable=True))
    op.add_column("student_videos", sa.Column("coach_comment", sa.Text(), nullable=True))
    op.add_column(
        "student_videos",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "student_videos",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "student_videos",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "student_videos",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        op.f("ix_student_videos_status"),
        "student_videos",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_student_videos_status"), table_name="student_videos")
    op.drop_column("student_videos", "updated_at")
    op.drop_column("student_videos", "completed_at")
    op.drop_column("student_videos", "submitted_at")
    op.drop_column("student_videos", "started_at")
    op.drop_column("student_videos", "coach_comment")
    op.drop_column("student_videos", "student_comment")
    op.drop_column("student_videos", "status")
    assignment_status.drop(op.get_bind(), checkfirst=True)
