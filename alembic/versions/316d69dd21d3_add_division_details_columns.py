"""add_division_details_columns

Revision ID: 316d69dd21d3
Revises: 8df1710aa460
Create Date: 2026-06-09 17:16:21.961928

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '316d69dd21d3'
down_revision: Union[str, None] = '8df1710aa460'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("divisions")}
    
    if "headquarters" not in columns:
        op.add_column("divisions", sa.Column("headquarters", sa.String(), nullable=True))
    if "description" not in columns:
        op.add_column("divisions", sa.Column("description", sa.String(), nullable=True))
    if "status" not in columns:
        op.add_column("divisions", sa.Column("status", sa.String(), nullable=True, server_default="Active"))


def downgrade() -> None:
    op.drop_column("divisions", "status")
    op.drop_column("divisions", "description")
    op.drop_column("divisions", "headquarters")
