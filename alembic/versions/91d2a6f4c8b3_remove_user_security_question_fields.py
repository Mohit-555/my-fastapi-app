"""remove_user_security_question_fields

Revision ID: 91d2a6f4c8b3
Revises: 4f2f5d8e9c01
Create Date: 2026-06-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "91d2a6f4c8b3"
down_revision: Union[str, None] = "4f2f5d8e9c01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("users"):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    if "security_answer_hash" in existing_columns:
        op.drop_column("users", "security_answer_hash")
    if "security_question" in existing_columns:
        op.drop_column("users", "security_question")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("users"):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    if "security_question" not in existing_columns:
        op.add_column("users", sa.Column("security_question", sa.String(length=255), nullable=True))
    if "security_answer_hash" not in existing_columns:
        op.add_column("users", sa.Column("security_answer_hash", sa.String(), nullable=True))
