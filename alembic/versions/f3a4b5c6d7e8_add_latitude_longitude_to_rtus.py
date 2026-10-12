"""add_latitude_longitude_to_rtus

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-10-09 23:15:00.000000

Adds latitude and longitude columns to the rtus table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rtus", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("rtus", sa.Column("longitude", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("rtus", "longitude")
    op.drop_column("rtus", "latitude")

