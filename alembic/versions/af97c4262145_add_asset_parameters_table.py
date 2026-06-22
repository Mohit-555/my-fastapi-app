"""add asset_parameters table
 
Revision ID: af97c4262145
Revises: edb2cddd02f8
Create Date: 2026-06-22 07:58:15.214460

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'af97c4262145'
down_revision: Union[str, None] = 'edb2cddd02f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_parameters",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("para_id", sa.String(length=8), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("prloc", sa.String(length=50), nullable=True),
        sa.Column("is_assigned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("para_id", name="uq_asset_parameters_para_id"),
    )
    op.create_index(
        "ix_asset_parameters_para_id", "asset_parameters", ["para_id"], unique=True
    )
    op.create_index(
        "ix_asset_parameters_asset_id", "asset_parameters", ["asset_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_asset_parameters_asset_id", table_name="asset_parameters")
    op.drop_index("ix_asset_parameters_para_id", table_name="asset_parameters")
    op.drop_table("asset_parameters")
