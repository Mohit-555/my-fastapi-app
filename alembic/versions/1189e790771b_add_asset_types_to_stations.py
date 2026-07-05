"""add asset_types to stations

Revision ID: 1189e790771b
Revises: 48f4269f2bf6
Create Date: 2026-07-05 19:16:28.242435

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1189e790771b'
down_revision: Union[str, None] = '48f4269f2bf6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('stations', sa.Column('asset_types', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('stations', 'asset_types')
