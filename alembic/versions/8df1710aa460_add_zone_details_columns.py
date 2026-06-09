"""add_zone_details_columns

Revision ID: 8df1710aa460
Revises: 5ece5ce07a3d
Create Date: 2026-06-09 17:07:55.181274

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8df1710aa460'
down_revision: Union[str, None] = '5ece5ce07a3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("zones")}
    
    if "headquarters" not in columns:
        op.add_column("zones", sa.Column("headquarters", sa.String(), nullable=True))
    if "description" not in columns:
        op.add_column("zones", sa.Column("description", sa.String(), nullable=True))
    if "status" not in columns:
        op.add_column("zones", sa.Column("status", sa.String(), nullable=True, server_default="Active"))


def downgrade() -> None:
    op.drop_column("zones", "status")
    op.drop_column("zones", "description")
    op.drop_column("zones", "headquarters")
