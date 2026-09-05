"""add_has_auto_hook_to_clips

Migration ini sudah dijalankan di DB dari sesi sebelumnya. File stub ini
dibuat agar Alembic bisa tracking chain revision dengan benar.

Revision ID: f2a3b4c5d6e7
Revises: e6f7a8b9c0d1
Create Date: 2026-09-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Kolom has_auto_hook sudah ada di DB — stub untuk Alembic tracking saja.
    pass


def downgrade() -> None:
    op.drop_column("clips", "has_auto_hook")
