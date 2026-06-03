"""add_alert_history_fields

Revision ID: b8d92f4c61e7
Revises: a71c24e9d3b0
Create Date: 2026-06-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8d92f4c61e7"
down_revision: Union[str, None] = "a71c24e9d3b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {col["name"] for col in inspector.get_columns("alert_events")}

    if "alert_status" not in existing_columns:
        op.add_column(
            "alert_events",
            sa.Column("alert_status", sa.String(length=20), nullable=False, server_default="Active"),
        )
    if "rectification_time" not in existing_columns:
        op.add_column("alert_events", sa.Column("rectification_time", sa.DateTime(), nullable=True))
    if "feedback_time" not in existing_columns:
        op.add_column("alert_events", sa.Column("feedback_time", sa.DateTime(), nullable=True))
    if "maintainer_name" not in existing_columns:
        op.add_column("alert_events", sa.Column("maintainer_name", sa.String(length=100), nullable=True))
    if "designation" not in existing_columns:
        op.add_column("alert_events", sa.Column("designation", sa.String(length=100), nullable=True))
    if "mobile" not in existing_columns:
        op.add_column("alert_events", sa.Column("mobile", sa.String(length=20), nullable=True))

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("alert_events")}
    indexes = [
        ("ix_alert_events_alert_status", ["alert_status"]),
        ("ix_alert_events_rectification_time", ["rectification_time"]),
        ("ix_alert_events_feedback_time", ["feedback_time"]),
    ]
    for name, columns in indexes:
        if name not in existing_indexes:
            op.create_index(name, "alert_events", columns, unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_alert_events_feedback_time"), table_name="alert_events")
    op.drop_index(op.f("ix_alert_events_rectification_time"), table_name="alert_events")
    op.drop_index(op.f("ix_alert_events_alert_status"), table_name="alert_events")

    op.drop_column("alert_events", "mobile")
    op.drop_column("alert_events", "designation")
    op.drop_column("alert_events", "maintainer_name")
    op.drop_column("alert_events", "feedback_time")
    op.drop_column("alert_events", "rectification_time")
    op.drop_column("alert_events", "alert_status")
