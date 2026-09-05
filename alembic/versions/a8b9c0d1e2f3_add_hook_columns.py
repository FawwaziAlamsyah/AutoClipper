"""add_hook_columns

Tambah kolom Auto Hook Engine:
- candidates: hook_moment_start, hook_moment_end, hook_type, hook_confidence, hook_caption
- clips: hook_applied, hook_skip_reason
- categories: preferred_hook_strategy

Revision ID: a8b9c0d1e2f3
Revises: e6f7a8b9c0d1
Create Date: 2026-09-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # candidates — hook moment dari LLM
    op.add_column("candidates", sa.Column("hook_moment_start", sa.Float(), nullable=True))
    op.add_column("candidates", sa.Column("hook_moment_end",   sa.Float(), nullable=True))
    op.add_column("candidates", sa.Column("hook_type",         sa.Text(),  nullable=True))
    op.add_column("candidates", sa.Column("hook_confidence",   sa.Float(), nullable=True))
    op.add_column("candidates", sa.Column("hook_caption",      sa.Text(),  nullable=True))

    # clips — apakah hook diterapkan dan kenapa tidak (kalau tidak)
    op.add_column("clips", sa.Column(
        "hook_applied",
        sa.Boolean(),
        nullable=False,
        server_default="false",
    ))
    op.add_column("clips", sa.Column("hook_skip_reason", sa.Text(), nullable=True))

    # categories — strategi hook foreground (fase depan, belum aktif)
    op.add_column("categories", sa.Column("preferred_hook_strategy", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("categories", "preferred_hook_strategy")
    op.drop_column("clips", "hook_skip_reason")
    op.drop_column("clips", "hook_applied")
    op.drop_column("candidates", "hook_caption")
    op.drop_column("candidates", "hook_confidence")
    op.drop_column("candidates", "hook_type")
    op.drop_column("candidates", "hook_moment_end")
    op.drop_column("candidates", "hook_moment_start")
