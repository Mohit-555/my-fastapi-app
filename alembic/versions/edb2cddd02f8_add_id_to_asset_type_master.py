"""add id to asset_type_master

Revision ID: edb2cddd02f8
Revises: 464fec6f2d1f
Create Date: 2026-06-15 14:21:41.355755

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'edb2cddd02f8'
down_revision: Union[str, None] = '464fec6f2d1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop the dependent foreign keys on child tables
    op.drop_constraint('alert_cause_master_asset_type_id_fkey', 'alert_cause_master', type_='foreignkey')
    op.drop_constraint('assets_asset_type_hex_fkey', 'assets', type_='foreignkey')

    # 2. Drop the primary key on parent
    op.drop_constraint('asset_type_master_pkey', 'asset_type_master', type_='primary')

    # 3. Add id column as identity (autoincrementing)
    op.add_column('asset_type_master', sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False))

    # 4. Create new primary key on 'id'
    op.create_primary_key('asset_type_master_pkey', 'asset_type_master', ['id'])
    op.create_index(op.f('ix_asset_type_master_id'), 'asset_type_master', ['id'], unique=False)

    # 5. Create unique constraint on 'asset_type_id'
    op.create_unique_constraint('uq_asset_type_master_type_id', 'asset_type_master', ['asset_type_id'])

    # 6. Re-create the foreign keys on child tables pointing to 'asset_type_id'
    op.create_foreign_key('alert_cause_master_asset_type_id_fkey', 'alert_cause_master', 'asset_type_master', ['asset_type_id'], ['asset_type_id'])
    op.create_foreign_key('assets_asset_type_hex_fkey', 'assets', 'asset_type_master', ['asset_type_hex'], ['asset_type_id'])


def downgrade() -> None:
    # 1. Drop foreign keys referencing asset_type_id unique constraint
    op.drop_constraint('alert_cause_master_asset_type_id_fkey', 'alert_cause_master', type_='foreignkey')
    op.drop_constraint('assets_asset_type_hex_fkey', 'assets', type_='foreignkey')

    # 2. Drop unique and primary constraints on parent
    op.drop_constraint('uq_asset_type_master_type_id', 'asset_type_master', type_='unique')
    op.drop_index(op.f('ix_asset_type_master_id'), table_name='asset_type_master')
    op.drop_constraint('asset_type_master_pkey', 'asset_type_master', type_='primary')

    # 3. Drop 'id' column
    op.drop_column('asset_type_master', 'id')

    # 4. Re-create primary key constraint on 'asset_type_id'
    op.create_primary_key('asset_type_master_pkey', 'asset_type_master', ['asset_type_id'])

    # 5. Re-create foreign keys pointing to parent primary key 'asset_type_id'
    op.create_foreign_key('alert_cause_master_asset_type_id_fkey', 'alert_cause_master', 'asset_type_master', ['asset_type_id'], ['asset_type_id'])
    op.create_foreign_key('assets_asset_type_hex_fkey', 'assets', 'asset_type_master', ['asset_type_hex'], ['asset_type_id'])
