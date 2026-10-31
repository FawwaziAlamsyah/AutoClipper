"""add_ai_content_brief_to_jobs

Revision ID: b2c3d4e5f6a7
Revises: a1c2e3f4a5b6
Create Date: 2026-10-31 18:58:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1c2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("ai_content_brief", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "ai_content_brief")
