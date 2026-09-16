"""assignments_and_submissions

Revision ID: c3d7e1a94f20
Revises: 8a6f2d9c4b10
Create Date: 2026-09-17 00:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c3d7e1a94f20"
down_revision: Union[str, None] = "8a6f2d9c4b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE assignmentstatus ADD VALUE IF NOT EXISTS 'revision_requested'")

    assignment_status = postgresql.ENUM(
        "assigned",
        "in_progress",
        "submitted",
        "completed",
        "revision_requested",
        name="assignmentstatus",
        create_type=False,
    )
    submission_status = postgresql.ENUM(
        "draft",
        "submitted",
        "revision_requested",
        "accepted",
        name="submissionstatus",
        create_type=False,
    )
    submission_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "assignments",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("exercise_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", assignment_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assignments_org_id", "assignments", ["org_id"], unique=False)
    op.create_index("ix_assignments_student_id", "assignments", ["student_id"], unique=False)
    op.create_index("ix_assignments_exercise_id", "assignments", ["exercise_id"], unique=False)
    op.create_index("ix_assignments_due_at", "assignments", ["due_at"], unique=False)
    op.create_index("ix_assignments_status", "assignments", ["status"], unique=False)

    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", submission_status, nullable=False),
        sa.Column("student_comment", sa.Text(), nullable=True),
        sa.Column("coach_comment", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "attempt", name="uq_submissions_assignment_attempt"),
        sa.UniqueConstraint("video_id", name="uq_submissions_video_id"),
    )
    op.create_index("ix_submissions_assignment_id", "submissions", ["assignment_id"], unique=False)
    op.create_index("ix_submissions_status", "submissions", ["status"], unique=False)
    op.create_index(
        "uq_submissions_one_accepted",
        "submissions",
        ["assignment_id"],
        unique=True,
        postgresql_where=sa.text("status = 'accepted'"),
    )

    op.execute(
        """
        INSERT INTO assignments (
            id, org_id, student_id, title, due_at, status,
            started_at, completed_at, created_at, updated_at
        )
        SELECT
            sv.video_id,
            v.org_id,
            sv.student_id,
            COALESCE(NULLIF(sv.exercise_name, ''), v.original_name),
            CASE
                WHEN sv.training_date IS NULL THEN NULL
                ELSE sv.training_date::timestamp AT TIME ZONE 'UTC'
            END,
            sv.status,
            sv.started_at,
            sv.completed_at,
            sv.created_at,
            sv.updated_at
        FROM student_videos AS sv
        JOIN videos AS v ON v.id = sv.video_id
        """
    )
    op.execute(
        """
        INSERT INTO submissions (
            id, assignment_id, video_id, attempt, status,
            student_comment, coach_comment, submitted_at, reviewed_at,
            created_at, updated_at
        )
        SELECT
            sv.video_id,
            sv.video_id,
            sv.video_id,
            1,
            CASE sv.status::text
                WHEN 'submitted' THEN 'submitted'::submissionstatus
                WHEN 'completed' THEN 'accepted'::submissionstatus
                ELSE 'draft'::submissionstatus
            END,
            sv.student_comment,
            sv.coach_comment,
            sv.submitted_at,
            CASE WHEN sv.status::text = 'completed' THEN sv.completed_at ELSE NULL END,
            sv.created_at,
            sv.updated_at
        FROM student_videos AS sv
        """
    )
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('assignments', 'id'),
            COALESCE((SELECT max(id) FROM assignments), 1),
            EXISTS (SELECT 1 FROM assignments)
        )
        """
    )
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('submissions', 'id'),
            COALESCE((SELECT max(id) FROM submissions), 1),
            EXISTS (SELECT 1 FROM submissions)
        )
        """
    )
    op.execute(
        """
        UPDATE notifications
        SET url = regexp_replace(url, '^/student/videos/', '/student/assignments/')
        WHERE url LIKE '/student/videos/%'
        """
    )
    op.drop_table("student_videos")


def downgrade() -> None:
    bind = op.get_bind()
    unsupported = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM assignments AS a
            LEFT JOIN submissions AS s ON s.assignment_id = a.id
            GROUP BY a.id
            HAVING count(s.id) <> 1
            LIMIT 1
            """
        )
    ).first()
    if unsupported is not None:
        raise RuntimeError(
            "cannot downgrade assignments with zero or multiple submissions to StudentVideo"
        )

    assignment_status = postgresql.ENUM(
        "assigned",
        "in_progress",
        "submitted",
        "completed",
        "revision_requested",
        name="assignmentstatus",
        create_type=False,
    )
    op.create_table(
        "student_videos",
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("exercise_name", sa.String(length=200), nullable=True),
        sa.Column("training_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("status", assignment_status, nullable=False),
        sa.Column("student_comment", sa.Text(), nullable=True),
        sa.Column("coach_comment", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("video_id"),
    )
    op.create_index("ix_student_videos_student_id", "student_videos", ["student_id"], unique=False)
    op.create_index("ix_student_videos_status", "student_videos", ["status"], unique=False)
    op.execute(
        """
        INSERT INTO student_videos (
            video_id, student_id, exercise_name, training_date, status,
            student_comment, coach_comment, started_at, submitted_at,
            completed_at, created_at, updated_at
        )
        SELECT
            s.video_id,
            a.student_id,
            a.title,
            a.due_at::date,
            CASE
                WHEN a.status::text = 'revision_requested' THEN 'in_progress'::assignmentstatus
                ELSE a.status
            END,
            s.student_comment,
            s.coach_comment,
            a.started_at,
            s.submitted_at,
            a.completed_at,
            a.created_at,
            a.updated_at
        FROM assignments AS a
        JOIN submissions AS s ON s.assignment_id = a.id
        """
    )
    op.execute(
        """
        UPDATE notifications
        SET url = regexp_replace(url, '^/student/assignments/', '/student/videos/')
        WHERE url LIKE '/student/assignments/%'
        """
    )

    op.drop_index("uq_submissions_one_accepted", table_name="submissions")
    op.drop_index("ix_submissions_status", table_name="submissions")
    op.drop_index("ix_submissions_assignment_id", table_name="submissions")
    op.drop_table("submissions")
    op.drop_index("ix_assignments_status", table_name="assignments")
    op.drop_index("ix_assignments_due_at", table_name="assignments")
    op.drop_index("ix_assignments_exercise_id", table_name="assignments")
    op.drop_index("ix_assignments_student_id", table_name="assignments")
    op.drop_index("ix_assignments_org_id", table_name="assignments")
    op.drop_table("assignments")
    postgresql.ENUM(name="submissionstatus").drop(op.get_bind(), checkfirst=True)
