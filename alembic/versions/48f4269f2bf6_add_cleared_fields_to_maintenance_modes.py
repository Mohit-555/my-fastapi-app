"""add_cleared_fields_to_maintenance_modes

Revision ID: 48f4269f2bf6
Revises: 722668d9b1fa
Create Date: 2026-06-24 18:12:28.034008

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '48f4269f2bf6'
down_revision: Union[str, None] = '722668d9b1fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('maintenance_modes', sa.Column('is_cleared', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('maintenance_modes', sa.Column('cleared_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('maintenance_modes', 'cleared_at')
    op.drop_column('maintenance_modes', 'is_cleared')
