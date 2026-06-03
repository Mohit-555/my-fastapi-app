"""add_remember_me_to_refresh_tokens

Revision ID: 2c9e7b1a5d03
Revises: f0a8b6c2d4e9
Create Date: 2026-06-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2c9e7b1a5d03"
down_revision: Union[str, None] = "f0a8b6c2d4e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("refresh_tokens"):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("refresh_tokens")}
    if "remember_me" not in existing_columns:
        op.add_column(
            "refresh_tokens",
            sa.Column("remember_me", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("refresh_tokens"):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("refresh_tokens")}
    if "remember_me" in existing_columns:
        op.drop_column("refresh_tokens", "remember_me")
