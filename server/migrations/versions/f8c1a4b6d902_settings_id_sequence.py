"""settings_id_sequence

Revision ID: f8c1a4b6d902
Revises: e7a2c9d4f610
Create Date: 2026-09-16 19:15:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f8c1a4b6d902"
down_revision: Union[str, None] = "e7a2c9d4f610"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS app_settings_id_seq")
    op.execute("ALTER SEQUENCE app_settings_id_seq OWNED BY app_settings.id")
    op.execute(
        "SELECT setval('app_settings_id_seq', "
        "GREATEST(COALESCE((SELECT MAX(id) FROM app_settings), 0), 1), "
        "COALESCE((SELECT MAX(id) FROM app_settings), 0) > 0)"
    )
    op.execute(
        "ALTER TABLE app_settings ALTER COLUMN id "
        "SET DEFAULT nextval('app_settings_id_seq')"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE app_settings ALTER COLUMN id DROP DEFAULT")
    op.execute("DROP SEQUENCE IF EXISTS app_settings_id_seq")
