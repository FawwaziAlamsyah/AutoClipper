"""add_category_id_to_training_runs

Revision ID: f1a2b3c4d5e6
Revises: 7c8d9e0f1a2b
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = '7c8d9e0f1a2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'training_runs',
        sa.Column('category_id', sa.Integer(), nullable=False),
    )
    op.create_foreign_key(
        'fk_training_runs_category_id',
        'training_runs',
        'categories',
        ['category_id'],
        ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_training_runs_category_id', 'training_runs', type_='foreignkey')
    op.drop_column('training_runs', 'category_id')
