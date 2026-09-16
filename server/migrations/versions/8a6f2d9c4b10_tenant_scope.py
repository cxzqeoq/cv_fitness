"""tenant_scope

Revision ID: 8a6f2d9c4b10
Revises: 4dbbb8d7a591
Create Date: 2026-09-17 00:00:00.000000
"""
import os
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "8a6f2d9c4b10"
down_revision: Union[str, None] = "4dbbb8d7a591"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TENANT_TABLES = (
    "app_settings",
    "students",
    "team_members",
    "videos",
    "exercises",
    "notifications",
    "audit_events",
)


def _bootstrap_org_id(bind) -> uuid.UUID:
    row_count = sum(
        bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in _TENANT_TABLES
    )
    raw = os.environ.get("BOOTSTRAP_ORG_ID", "").strip()
    if not raw:
        if row_count:
            raise RuntimeError(
                "BOOTSTRAP_ORG_ID is required to tenant-scope existing Fitness data"
            )
        return uuid.UUID("00000000-0000-0000-0000-000000000001")
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise RuntimeError("BOOTSTRAP_ORG_ID must be a UUID") from exc


def upgrade() -> None:
    bind = op.get_bind()
    bootstrap_org_id = _bootstrap_org_id(bind)

    account_count = bind.execute(sa.text("SELECT count(*) FROM student_accounts")).scalar_one()
    if account_count:
        raise RuntimeError(
            "student_accounts must be migrated to omra.is before the tenant/OIDC cutover"
        )

    for table in _TENANT_TABLES:
        op.add_column(
            table,
            sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        bind.execute(
            sa.text(f"UPDATE {table} SET org_id = :org_id WHERE org_id IS NULL"),
            {"org_id": bootstrap_org_id},
        )
        op.alter_column(table, "org_id", nullable=False)
        op.create_index(f"ix_{table}_org_id", table, ["org_id"], unique=False)

    op.add_column("team_members", sa.Column("oidc_sub", sa.String(length=200), nullable=True))
    bind.execute(
        sa.text(
            """
            UPDATE team_members
            SET oidc_sub = staff_identities.oidc_sub
            FROM staff_identities
            WHERE staff_identities.team_member_id = team_members.id
            """
        )
    )
    op.add_column("students", sa.Column("oidc_sub", sa.String(length=200), nullable=True))

    duplicate_student_email = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM students
            WHERE email IS NOT NULL
            GROUP BY org_id, lower(email)
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate_student_email is not None:
        raise RuntimeError("duplicate student emails must be resolved before tenant cutover")

    op.drop_index("ix_team_members_email", table_name="team_members")
    op.create_index("ix_team_members_email", "team_members", ["email"], unique=False)
    op.create_unique_constraint(
        "uq_team_members_org_email", "team_members", ["org_id", "email"]
    )
    op.create_unique_constraint(
        "uq_team_members_org_oidc_sub", "team_members", ["org_id", "oidc_sub"]
    )

    op.create_unique_constraint(
        "uq_students_org_email", "students", ["org_id", "email"]
    )
    op.create_unique_constraint(
        "uq_students_org_oidc_sub", "students", ["org_id", "oidc_sub"]
    )

    op.drop_index("ix_exercises_name", table_name="exercises")
    op.create_index("ix_exercises_name", "exercises", ["name"], unique=False)
    op.create_unique_constraint(
        "uq_exercises_org_name", "exercises", ["org_id", "name"]
    )
    op.create_unique_constraint("uq_app_settings_org", "app_settings", ["org_id"])

    op.drop_index("ix_notifications_recipient_unread", table_name="notifications")
    op.create_index(
        "ix_notifications_org_recipient_unread",
        "notifications",
        ["org_id", "recipient_kind", "recipient_id", "read_at"],
        unique=False,
    )

    op.drop_table("staff_identities")
    op.drop_table("student_accounts")


def downgrade() -> None:
    op.create_table(
        "staff_identities",
        sa.Column("team_member_id", sa.Integer(), nullable=False),
        sa.Column("oidc_sub", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["team_member_id"], ["team_members.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("team_member_id"),
    )
    op.create_index(
        "ix_staff_identities_oidc_sub",
        "staff_identities",
        ["oidc_sub"],
        unique=True,
    )
    op.execute(
        """
        INSERT INTO staff_identities (team_member_id, oidc_sub)
        SELECT id, oidc_sub FROM team_members WHERE oidc_sub IS NOT NULL
        """
    )
    op.create_table(
        "student_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_student_accounts_email", "student_accounts", ["email"], unique=True)
    op.create_index(
        "ix_student_accounts_student_id", "student_accounts", ["student_id"], unique=True
    )

    op.drop_index("ix_notifications_org_recipient_unread", table_name="notifications")
    op.create_index(
        "ix_notifications_recipient_unread",
        "notifications",
        ["recipient_kind", "recipient_id", "read_at"],
        unique=False,
    )

    op.drop_constraint("uq_app_settings_org", "app_settings", type_="unique")
    op.drop_constraint("uq_exercises_org_name", "exercises", type_="unique")
    op.drop_index("ix_exercises_name", table_name="exercises")
    op.create_index("ix_exercises_name", "exercises", ["name"], unique=True)
    op.drop_constraint("uq_students_org_oidc_sub", "students", type_="unique")
    op.drop_constraint("uq_students_org_email", "students", type_="unique")
    op.drop_constraint("uq_team_members_org_oidc_sub", "team_members", type_="unique")
    op.drop_constraint("uq_team_members_org_email", "team_members", type_="unique")
    op.drop_index("ix_team_members_email", table_name="team_members")
    op.create_index("ix_team_members_email", "team_members", ["email"], unique=True)

    op.drop_column("students", "oidc_sub")
    op.drop_column("team_members", "oidc_sub")
    for table in reversed(_TENANT_TABLES):
        op.drop_index(f"ix_{table}_org_id", table_name=table)
        op.drop_column(table, "org_id")
