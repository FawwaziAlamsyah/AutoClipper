"""add_tiktok_uploaded_to_clips

Revision ID: b5c6d7e8f9a0
Revises: a3b4c5d6e7f8
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b5c6d7e8f9a0'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "clips",
        sa.Column("tiktok_uploaded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("clips", "tiktok_uploaded")
