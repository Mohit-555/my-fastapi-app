"""add_asset_inventory_table

Revision ID: 9b7f2c1a4d6e
Revises: 236665569b2e
Create Date: 2026-05-31 17:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9b7f2c1a4d6e"
down_revision: Union[str, None] = "236665569b2e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("asset_inventory"):
        op.create_table(
            "asset_inventory",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("station_id", sa.Integer(), nullable=False),
            sa.Column("asset_type_hex", sa.String(length=2), nullable=False),
            sa.Column("asset_make", sa.String(length=80), nullable=False),
            sa.Column("count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["station_id"], ["stations.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "station_id",
                "asset_type_hex",
                "asset_make",
                name="uq_asset_inventory_station_type_make",
            ),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("asset_inventory")}
    indexes = [
        ("ix_asset_inventory_id", ["id"]),
        ("ix_asset_inventory_station_id", ["station_id"]),
        ("ix_asset_inventory_asset_type_hex", ["asset_type_hex"]),
        ("ix_asset_inventory_asset_make", ["asset_make"]),
    ]
    for name, columns in indexes:
        if name not in existing_indexes:
            op.create_index(name, "asset_inventory", columns, unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_asset_inventory_asset_make"), table_name="asset_inventory")
    op.drop_index(op.f("ix_asset_inventory_asset_type_hex"), table_name="asset_inventory")
    op.drop_index(op.f("ix_asset_inventory_station_id"), table_name="asset_inventory")
    op.drop_index(op.f("ix_asset_inventory_id"), table_name="asset_inventory")
    op.drop_table("asset_inventory")
