"""programs_lessons_and_enrollments

Revision ID: d5f1b8a207c4
Revises: c3d7e1a94f20
Create Date: 2026-09-17 02:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d5f1b8a207c4"
down_revision: Union[str, None] = "c3d7e1a94f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE assignmentstatus ADD VALUE IF NOT EXISTS 'locked' BEFORE 'assigned'")

    program_status = postgresql.ENUM(
        "draft",
        "published",
        "archived",
        name="programstatus",
        create_type=False,
    )
    enrollment_status = postgresql.ENUM(
        "active",
        "paused",
        "completed",
        "cancelled",
        name="enrollmentstatus",
        create_type=False,
    )
    program_status.create(op.get_bind(), checkfirst=True)
    enrollment_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "programs",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", program_status, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_programs_org_id", "programs", ["org_id"], unique=False)
    op.create_index("ix_programs_title", "programs", ["title"], unique=False)
    op.create_index("ix_programs_status", "programs", ["status"], unique=False)

    op.create_table(
        "lessons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("program_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("unlock_offset_days", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("program_id", "position", name="uq_lessons_program_position"),
    )
    op.create_index("ix_lessons_program_id", "lessons", ["program_id"], unique=False)

    op.create_table(
        "lesson_exercises",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lesson_id", sa.Integer(), nullable=False),
        sa.Column("exercise_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("target_sets", sa.Integer(), nullable=True),
        sa.Column("target_reps", sa.Integer(), nullable=True),
        sa.Column("target_duration_sec", sa.Integer(), nullable=True),
        sa.Column("reference_segment_id", sa.Integer(), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reference_segment_id"], ["segments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lesson_id", "position", name="uq_lesson_exercises_lesson_position"),
    )
    op.create_index("ix_lesson_exercises_lesson_id", "lesson_exercises", ["lesson_id"], unique=False)
    op.create_index("ix_lesson_exercises_exercise_id", "lesson_exercises", ["exercise_id"], unique=False)

    op.create_table(
        "enrollments",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("program_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", enrollment_status, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_enrollments_org_id", "enrollments", ["org_id"], unique=False)
    op.create_index("ix_enrollments_program_id", "enrollments", ["program_id"], unique=False)
    op.create_index("ix_enrollments_student_id", "enrollments", ["student_id"], unique=False)
    op.create_index("ix_enrollments_starts_at", "enrollments", ["starts_at"], unique=False)
    op.create_index("ix_enrollments_status", "enrollments", ["status"], unique=False)

    op.add_column("assignments", sa.Column("enrollment_id", sa.Integer(), nullable=True))
    op.add_column("assignments", sa.Column("lesson_exercise_id", sa.Integer(), nullable=True))
    op.add_column("assignments", sa.Column("available_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_assignments_enrollment_id",
        "assignments",
        "enrollments",
        ["enrollment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_assignments_lesson_exercise_id",
        "assignments",
        "lesson_exercises",
        ["lesson_exercise_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_assignments_enrollment_lesson_exercise",
        "assignments",
        ["enrollment_id", "lesson_exercise_id"],
    )
    op.create_index("ix_assignments_enrollment_id", "assignments", ["enrollment_id"], unique=False)
    op.create_index("ix_assignments_lesson_exercise_id", "assignments", ["lesson_exercise_id"], unique=False)
    op.create_index("ix_assignments_available_at", "assignments", ["available_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_assignments_available_at", table_name="assignments")
    op.drop_index("ix_assignments_lesson_exercise_id", table_name="assignments")
    op.drop_index("ix_assignments_enrollment_id", table_name="assignments")
    op.drop_constraint("uq_assignments_enrollment_lesson_exercise", "assignments", type_="unique")
    op.drop_constraint("fk_assignments_lesson_exercise_id", "assignments", type_="foreignkey")
    op.drop_constraint("fk_assignments_enrollment_id", "assignments", type_="foreignkey")
    op.drop_column("assignments", "available_at")
    op.drop_column("assignments", "lesson_exercise_id")
    op.drop_column("assignments", "enrollment_id")

    op.drop_index("ix_enrollments_status", table_name="enrollments")
    op.drop_index("ix_enrollments_starts_at", table_name="enrollments")
    op.drop_index("ix_enrollments_student_id", table_name="enrollments")
    op.drop_index("ix_enrollments_program_id", table_name="enrollments")
    op.drop_index("ix_enrollments_org_id", table_name="enrollments")
    op.drop_table("enrollments")
    op.drop_index("ix_lesson_exercises_exercise_id", table_name="lesson_exercises")
    op.drop_index("ix_lesson_exercises_lesson_id", table_name="lesson_exercises")
    op.drop_table("lesson_exercises")
    op.drop_index("ix_lessons_program_id", table_name="lessons")
    op.drop_table("lessons")
    op.drop_index("ix_programs_status", table_name="programs")
    op.drop_index("ix_programs_title", table_name="programs")
    op.drop_index("ix_programs_org_id", table_name="programs")
    op.drop_table("programs")
    postgresql.ENUM(name="enrollmentstatus").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="programstatus").drop(op.get_bind(), checkfirst=True)
