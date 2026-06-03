"""add_alert_events_table

Revision ID: a71c24e9d3b0
Revises: 9b7f2c1a4d6e
Create Date: 2026-05-31 18:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a71c24e9d3b0"
down_revision: Union[str, None] = "9b7f2c1a4d6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("alert_events"):
        op.create_table(
            "alert_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("station_id", sa.Integer(), nullable=False),
            sa.Column("alert_type", sa.String(length=20), nullable=False),
            sa.Column("asset_type_hex", sa.String(length=2), nullable=False),
            sa.Column("asset_no", sa.String(length=40), nullable=False),
            sa.Column("cause", sa.String(length=100), nullable=False),
            sa.Column("feedback", sa.String(length=2), nullable=True),
            sa.Column("acknowledged", sa.Boolean(), nullable=False),
            sa.Column("remark", sa.Text(), nullable=True),
            sa.Column("alert_time", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["station_id"], ["stations.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("alert_events")}
    indexes = [
        ("ix_alert_events_id", ["id"]),
        ("ix_alert_events_station_id", ["station_id"]),
        ("ix_alert_events_alert_type", ["alert_type"]),
        ("ix_alert_events_asset_type_hex", ["asset_type_hex"]),
        ("ix_alert_events_asset_no", ["asset_no"]),
        ("ix_alert_events_cause", ["cause"]),
        ("ix_alert_events_feedback", ["feedback"]),
        ("ix_alert_events_alert_time", ["alert_time"]),
    ]
    for name, columns in indexes:
        if name not in existing_indexes:
            op.create_index(name, "alert_events", columns, unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_alert_events_alert_time"), table_name="alert_events")
    op.drop_index(op.f("ix_alert_events_feedback"), table_name="alert_events")
    op.drop_index(op.f("ix_alert_events_cause"), table_name="alert_events")
    op.drop_index(op.f("ix_alert_events_asset_no"), table_name="alert_events")
    op.drop_index(op.f("ix_alert_events_asset_type_hex"), table_name="alert_events")
    op.drop_index(op.f("ix_alert_events_alert_type"), table_name="alert_events")
    op.drop_index(op.f("ix_alert_events_station_id"), table_name="alert_events")
    op.drop_index(op.f("ix_alert_events_id"), table_name="alert_events")
    op.drop_table("alert_events")
