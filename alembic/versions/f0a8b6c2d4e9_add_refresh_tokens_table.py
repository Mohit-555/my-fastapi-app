"""add_refresh_tokens_table

Revision ID: f0a8b6c2d4e9
Revises: 91d2a6f4c8b3
Create Date: 2026-06-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f0a8b6c2d4e9"
down_revision: Union[str, None] = "91d2a6f4c8b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("refresh_tokens"):
        op.create_table(
            "refresh_tokens",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("remember_me", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("refresh_tokens")}
    indexes = [
        ("ix_refresh_tokens_id", ["id"]),
        ("ix_refresh_tokens_user_id", ["user_id"]),
        ("ix_refresh_tokens_token_hash", ["token_hash"]),
        ("ix_refresh_tokens_expires_at", ["expires_at"]),
        ("ix_refresh_tokens_revoked_at", ["revoked_at"]),
    ]
    for name, columns in indexes:
        if name not in existing_indexes:
            op.create_index(name, "refresh_tokens", columns, unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_refresh_tokens_revoked_at"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_expires_at"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_token_hash"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
