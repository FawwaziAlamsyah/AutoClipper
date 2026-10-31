"""add_ai_discovery_columns

Revision ID: a1c2e3f4a5b6
Revises: e5f6a7b8c9d0
Create Date: 2026-10-31 16:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c2e3f4a5b6"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Tambah source ke candidates (default 'scoring')
    op.add_column(
        "candidates",
        sa.Column("source", sa.Text(), server_default="scoring", nullable=False),
    )

    # 2. Tambah ai_category_text dan ai_scan_visual ke jobs
    op.add_column(
        "jobs",
        sa.Column("ai_category_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("ai_scan_visual", sa.Boolean(), server_default=sa.text("true"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "ai_scan_visual")
    op.drop_column("jobs", "ai_category_text")
    op.drop_column("candidates", "source")
