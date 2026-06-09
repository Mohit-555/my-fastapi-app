"""add_station_details_columns

Revision ID: 82b7c7a1e4eb
Revises: 316d69dd21d3
Create Date: 2026-06-09 17:22:00.863000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '82b7c7a1e4eb'
down_revision: Union[str, None] = '316d69dd21d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("stations")}
    
    if "category" not in columns:
        op.add_column("stations", sa.Column("category", sa.String(), nullable=True))
    if "address" not in columns:
        op.add_column("stations", sa.Column("address", sa.String(), nullable=True))
    if "description" not in columns:
        op.add_column("stations", sa.Column("description", sa.String(), nullable=True))
    if "status" not in columns:
        op.add_column("stations", sa.Column("status", sa.String(), nullable=True, server_default="Active"))


def downgrade() -> None:
    op.drop_column("stations", "status")
    op.drop_column("stations", "description")
    op.drop_column("stations", "address")
    op.drop_column("stations", "category")
