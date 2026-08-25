"""add_edited_file_path_to_clips

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Tambah kolom edited_file_path ke tabel clips."""
    op.add_column(
        'clips',
        sa.Column('edited_file_path', sa.String(1024), nullable=True),
    )


def downgrade() -> None:
    """Hapus kolom edited_file_path dari tabel clips."""
    op.drop_column('clips', 'edited_file_path')
