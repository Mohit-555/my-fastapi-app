"""add_phase5_columns_and_indexes

Revision ID: e96aa4f26b5d
Revises: 56bb39f8a47c
Create Date: 2026-07-08 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision: str = 'e96aa4f26b5d'
down_revision: Union[str, None] = '56bb39f8a47c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name, column_name):
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    columns = [c['name'] for c in inspector.get_columns(table_name)]
    return column_name in columns


def index_exists(table_name, index_name):
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    indexes = [i['name'] for i in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade() -> None:
    # 1. Add missing columns safely
    if not column_exists('alert_events', 'escalated_to'):
        op.add_column('alert_events', sa.Column('escalated_to', sa.String(length=100), nullable=True))
    
    if not column_exists('alert_events', 'vendor_code'):
        op.add_column('alert_events', sa.Column('vendor_code', sa.String(length=20), nullable=True, server_default='XYZ'))
        
    if not column_exists('assets', 'vendor_code'):
        op.add_column('assets', sa.Column('vendor_code', sa.String(length=20), nullable=True, server_default='XYZ'))
        
    if not column_exists('assets', 'last_sync'):
        op.add_column('assets', sa.Column('last_sync', sa.DateTime(), nullable=True))

    # 2. Add performance indexes safely
    if not index_exists('alert_events', 'idx_alerts_time_status'):
        op.create_index('idx_alerts_time_status', 'alert_events', ['alert_time', 'alert_status'])
        
    if not index_exists('alert_events', 'idx_alerts_station_time'):
        op.create_index('idx_alerts_station_time', 'alert_events', ['station_id', 'alert_time'])
        
    if not index_exists('alert_events', 'idx_alerts_asset_cause'):
        op.create_index('idx_alerts_asset_cause', 'alert_events', ['asset_no', 'cause'])
        
    if not index_exists('asset_parameters', 'idx_asset_params_lookup'):
        op.create_index('idx_asset_params_lookup', 'asset_parameters', ['asset_id', 'para_id'])
        
    if not index_exists('assets', 'ix_assets_is_active'):
        op.create_index('ix_assets_is_active', 'assets', ['is_active'])
        
    if not index_exists('assets', 'ix_assets_vendor_code'):
        op.create_index('ix_assets_vendor_code', 'assets', ['vendor_code'])
        
    if not index_exists('alert_events', 'ix_alert_events_escalation_level'):
        op.create_index('ix_alert_events_escalation_level', 'alert_events', ['escalation_level'])
        
    if not index_exists('alert_events', 'ix_alert_events_vendor_code'):
        op.create_index('ix_alert_events_vendor_code', 'alert_events', ['vendor_code'])


def downgrade() -> None:
    # Remove indexes if they exist
    if index_exists('alert_events', 'ix_alert_events_vendor_code'):
        op.drop_index('ix_alert_events_vendor_code', 'alert_events')
        
    if index_exists('alert_events', 'ix_alert_events_escalation_level'):
        op.drop_index('ix_alert_events_escalation_level', 'alert_events')
        
    if index_exists('assets', 'ix_assets_vendor_code'):
        op.drop_index('ix_assets_vendor_code', 'assets')
        
    if index_exists('assets', 'ix_assets_is_active'):
        op.drop_index('ix_assets_is_active', 'assets')
        
    if index_exists('asset_parameters', 'idx_asset_params_lookup'):
        op.drop_index('idx_asset_params_lookup', 'asset_parameters')
        
    if index_exists('alert_events', 'idx_alerts_asset_cause'):
        op.drop_index('idx_alerts_asset_cause', 'alert_events')
        
    if index_exists('alert_events', 'idx_alerts_station_time'):
        op.drop_index('idx_alerts_station_time', 'alert_events')
        
    if index_exists('alert_events', 'idx_alerts_time_status'):
        op.drop_index('idx_alerts_time_status', 'alert_events')

    # Remove columns if they exist
    if column_exists('assets', 'last_sync'):
        op.drop_column('assets', 'last_sync')
        
    if column_exists('assets', 'vendor_code'):
        op.drop_column('assets', 'vendor_code')
        
    if column_exists('alert_events', 'vendor_code'):
        op.drop_column('alert_events', 'vendor_code')
        
    if column_exists('alert_events', 'escalated_to'):
        op.drop_column('alert_events', 'escalated_to')
