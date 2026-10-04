"""add_rtus_table_and_gateway_rtu_id

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-29 12:45:00.000000

Adds the rtus table representing physical RTU enclosures at stations,
and adds rtu_id foreign key on gateways table to link Master Cards to RTUs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create rtus table
    op.create_table(
        "rtus",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("station_id", sa.Integer(), nullable=False),
        sa.Column("rtu_name", sa.String(length=100), nullable=False),
        sa.Column("rtu_code", sa.String(length=50), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=False, server_default="Relay Room"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["station_id"], ["stations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("station_id", "rtu_name", name="uq_station_rtu_name"),
    )
    op.create_index(op.f("ix_rtus_id"), "rtus", ["id"], unique=False)
    op.create_index(op.f("ix_rtus_station_id"), "rtus", ["station_id"], unique=False)
    op.create_index(op.f("ix_rtus_rtu_code"), "rtus", ["rtu_code"], unique=True)

    # 2. Add rtu_id column to gateways table
    op.add_column("gateways", sa.Column("rtu_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_gateways_rtu_id", "gateways", "rtus", ["rtu_id"], ["id"], ondelete="SET NULL")
    op.create_index(op.f("ix_gateways_rtu_id"), "gateways", ["rtu_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_gateways_rtu_id"), table_name="gateways")
    op.drop_constraint("fk_gateways_rtu_id", "gateways", type_="foreignkey")
    op.drop_column("gateways", "rtu_id")

    op.drop_index(op.f("ix_rtus_rtu_code"), table_name="rtus")
    op.drop_index(op.f("ix_rtus_station_id"), table_name="rtus")
    op.drop_index(op.f("ix_rtus_id"), table_name="rtus")
    op.drop_table("rtus")
