"""add_onupdate_cascade_to_assets_gateway_fk

Revision ID: g1a2b3c4d5e6
Revises: f3a4b5c6d7e8
Create Date: 2026-11-12 06:50:00.000000

Adds ON UPDATE CASCADE to assets.station_gateway_id foreign key referencing gateways.stngw_id,
allowing gateway stngw_id updates to cascade automatically to dependent assets.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "g1a2b3c4d5e6"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            DO $$
            DECLARE
                fk_name text;
            BEGIN
                SELECT tc.constraint_name INTO fk_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_name = 'assets'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = 'station_gateway_id'
                LIMIT 1;

                IF fk_name IS NOT NULL THEN
                    EXECUTE format('ALTER TABLE assets DROP CONSTRAINT %I', fk_name);
                END IF;
            END $$;
            """
        )
        op.create_foreign_key(
            "assets_station_gateway_id_fkey",
            "assets",
            "gateways",
            ["station_gateway_id"],
            ["stngw_id"],
            onupdate="CASCADE",
        )
    else:
        with op.batch_alter_table("assets") as batch_op:
            batch_op.create_foreign_key(
                "assets_station_gateway_id_fkey",
                "gateways",
                ["station_gateway_id"],
                ["stngw_id"],
                onupdate="CASCADE",
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint("assets_station_gateway_id_fkey", "assets", type_="foreignkey")
        op.create_foreign_key(
            "assets_station_gateway_id_fkey",
            "assets",
            "gateways",
            ["station_gateway_id"],
            ["stngw_id"],
        )
    else:
        with op.batch_alter_table("assets") as batch_op:
            batch_op.drop_constraint("assets_station_gateway_id_fkey", type_="foreignkey")
            batch_op.create_foreign_key(
                "assets_station_gateway_id_fkey",
                "gateways",
                ["station_gateway_id"],
                ["stngw_id"],
            )
