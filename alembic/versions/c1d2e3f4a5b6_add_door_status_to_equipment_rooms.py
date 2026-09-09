"""add door_status to equipment_rooms

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-09-09 15:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "equipment_rooms",
        sa.Column("door_status", sa.String(length=10), server_default="CLOSED", nullable=True)
    )


def downgrade() -> None:
    op.drop_column("equipment_rooms", "door_status")
