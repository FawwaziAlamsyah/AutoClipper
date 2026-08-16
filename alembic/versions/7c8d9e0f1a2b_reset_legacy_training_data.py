"""reset_legacy_training_data

Revision ID: 7c8d9e0f1a2b
Revises: 5e6a73860bf6
Create Date: 2026-08-16 00:00:00.000000

PERHATIAN: Migrasi ini destruktif dan disengaja.
Seluruh data training lama di-reset karena belum memiliki kategori.
Sistem training diubah menjadi per-kategori dan dimulai dari nol.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7c8d9e0f1a2b'
down_revision: Union[str, Sequence[str], None] = '5e6a73860bf6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Reset seluruh data training lama — belum punya kategori, mulai dari nol."""
    op.execute("""
        UPDATE candidates
        SET is_training_example = false,
            actual_score = NULL,
            label_source = NULL
        WHERE is_training_example = true
    """)
    op.execute("DELETE FROM training_runs")


def downgrade() -> None:
    """No-op: data reset tidak dapat dikembalikan secara otomatis."""
    pass
