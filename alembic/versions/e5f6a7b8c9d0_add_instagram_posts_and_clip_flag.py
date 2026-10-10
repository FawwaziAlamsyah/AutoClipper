"""add_instagram_posts_and_clip_flag

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Tambah flag instagram_published di tabel clips
    op.add_column(
        "clips",
        sa.Column("instagram_published", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    # 2. Buat tabel instagram_posts untuk riwayat posting
    op.create_table(
        "instagram_posts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("clip_id", sa.Integer(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("share_to_feed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("container_id", sa.String(length=255), nullable=True),
        sa.Column("media_id", sa.String(length=255), nullable=True),
        sa.Column("permalink", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["clip_id"], ["clips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_instagram_posts_clip_id"), "instagram_posts", ["clip_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_instagram_posts_clip_id"), table_name="instagram_posts")
    op.drop_table("instagram_posts")
    op.drop_column("clips", "instagram_published")
