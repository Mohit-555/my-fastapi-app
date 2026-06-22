"""add telemetry unique constraint
 
Revision ID: 722668d9b1fa
Revises: af97c4262145
Create Date: 2026-06-22 07:58:26.697824

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '722668d9b1fa'
down_revision: Union[str, None] = 'af97c4262145'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: remove exact duplicate rows that may already exist, keeping
    # the earliest (lowest id) copy of each.
    op.execute("""
        DELETE FROM telemetry t1
        USING telemetry t2
        WHERE t1.id > t2.id
          AND t1.gateway_id = t2.gateway_id
          AND t1.para_id = t2.para_id
          AND t1.prt IS NOT DISTINCT FROM t2.prt
          AND t1.prv IS NOT DISTINCT FROM t2.prv
    """)

    # Step 2: add the unique constraint.
    op.create_unique_constraint(
        "uq_telemetry_gateway_para_prt_prv",
        "telemetry",
        ["gateway_id", "para_id", "prt", "prv"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_telemetry_gateway_para_prt_prv",
        "telemetry",
        type_="unique",
    )
