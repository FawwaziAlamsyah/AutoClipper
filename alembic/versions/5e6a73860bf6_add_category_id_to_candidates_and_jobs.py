"""add_category_id_to_candidates_and_jobs

Revision ID: 5e6a73860bf6
Revises: 9c1d2e3f4a5b
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5e6a73860bf6'
down_revision: Union[str, Sequence[str], None] = '9c1d2e3f4a5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('candidates', sa.Column('category_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_candidates_category_id',
        'candidates',
        'categories',
        ['category_id'],
        ['id'],
        ondelete='SET NULL'
    )

    op.add_column('jobs', sa.Column('category_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_jobs_category_id',
        'jobs',
        'categories',
        ['category_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_jobs_category_id', 'jobs', type_='foreignkey')
    op.drop_column('jobs', 'category_id')

    op.drop_constraint('fk_candidates_category_id', 'candidates', type_='foreignkey')
    op.drop_column('candidates', 'category_id')
