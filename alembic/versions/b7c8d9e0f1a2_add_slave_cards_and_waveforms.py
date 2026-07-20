"""add_slave_cards_channel_mapping_and_telemetry_waveforms

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-16 00:00:00.000000

Implements the hardware hierarchy confirmed in the RDPMS Architecture
Discussion (senior's answers):
  - Each Master Card is its own independent Gateway (already true — no
    change needed to `gateways`, imei column already existed).
  - Gateway (Master Card) -> multiple Slave Cards -> Channels -> para_id.
  - Raw waveform data should be stored for diagnostics/predictive
    maintenance -> new telemetry_waveforms table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "slave_cards",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("gateway_id", sa.Integer(), sa.ForeignKey("gateways.id"), nullable=False, index=True),
        sa.Column("card_address", sa.String(2), nullable=False),
        sa.Column("card_type", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("gateway_id", "card_address", "card_type", name="uq_slave_card_gw_addr_type"),
    )

    op.add_column("asset_parameters", sa.Column("slave_card_id", sa.Integer(), sa.ForeignKey("slave_cards.id"), nullable=True))
    op.add_column("asset_parameters", sa.Column("channel_number", sa.String(10), nullable=True))
    op.create_index("ix_asset_parameters_slave_card_id", "asset_parameters", ["slave_card_id"])

    op.create_table(
        "telemetry_waveforms",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("para_id", sa.String(8), nullable=False, index=True),
        sa.Column("prt", sa.String(30), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_telemetry_waveform_lookup", "telemetry_waveforms", ["para_id", "prt"])


def downgrade() -> None:
    op.drop_index("idx_telemetry_waveform_lookup", table_name="telemetry_waveforms")
    op.drop_table("telemetry_waveforms")

    op.drop_index("ix_asset_parameters_slave_card_id", table_name="asset_parameters")
    op.drop_column("asset_parameters", "channel_number")
    op.drop_column("asset_parameters", "slave_card_id")

    op.drop_table("slave_cards")
