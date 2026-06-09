"""add_maintenance_modes_table

Revision ID: 5ece5ce07a3d
Revises: 7d2a8d642107
Create Date: 2026-06-09 12:17:26.243388

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ece5ce07a3d'
down_revision: Union[str, None] = '7d2a8d642107'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('maintenance_modes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('station_id', sa.Integer(), nullable=False),
    sa.Column('asset_type_hex', sa.String(length=2), nullable=False),
    sa.Column('asset_no', sa.String(length=40), nullable=False),
    sa.Column('from_time', sa.DateTime(), nullable=False),
    sa.Column('to_time', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['station_id'], ['stations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_maintenance_modes_id'), 'maintenance_modes', ['id'], unique=False)
    op.create_index(op.f('ix_maintenance_modes_station_id'), 'maintenance_modes', ['station_id'], unique=False)
    op.create_index(op.f('ix_maintenance_modes_asset_type_hex'), 'maintenance_modes', ['asset_type_hex'], unique=False)
    op.create_index(op.f('ix_maintenance_modes_asset_no'), 'maintenance_modes', ['asset_no'], unique=False)
    op.create_index(op.f('ix_maintenance_modes_from_time'), 'maintenance_modes', ['from_time'], unique=False)
    op.create_index(op.f('ix_maintenance_modes_to_time'), 'maintenance_modes', ['to_time'], unique=False)
    op.create_index(op.f('ix_maintenance_modes_created_at'), 'maintenance_modes', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_maintenance_modes_created_at'), table_name='maintenance_modes')
    op.drop_index(op.f('ix_maintenance_modes_to_time'), table_name='maintenance_modes')
    op.drop_index(op.f('ix_maintenance_modes_from_time'), table_name='maintenance_modes')
    op.drop_index(op.f('ix_maintenance_modes_asset_no'), table_name='maintenance_modes')
    op.drop_index(op.f('ix_maintenance_modes_asset_type_hex'), table_name='maintenance_modes')
    op.drop_index(op.f('ix_maintenance_modes_station_id'), table_name='maintenance_modes')
    op.drop_index(op.f('ix_maintenance_modes_id'), table_name='maintenance_modes')
    op.drop_table('maintenance_modes')
