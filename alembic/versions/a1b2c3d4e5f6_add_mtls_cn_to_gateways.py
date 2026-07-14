"""add_mtls_cn_to_gateways

Revision ID: a1b2c3d4e5f6
Revises: e96aa4f26b5d
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "e96aa4f26b5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "gateways",
        sa.Column("mtls_cn", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gateways", "mtls_cn")
