"""add_users_table_auth_fields

Revision ID: 4f2f5d8e9c01
Revises: b8d92f4c61e7
Create Date: 2026-06-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4f2f5d8e9c01"
down_revision: Union[str, None] = "b8d92f4c61e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("full_name", sa.String(), nullable=False),
            sa.Column("employee_id", sa.String(length=50), nullable=False),
            sa.Column("designation", sa.String(length=50), nullable=False),
            sa.Column("zone_id", sa.Integer(), nullable=True),
            sa.Column("division_id", sa.Integer(), nullable=True),
            sa.Column("mobile_number", sa.String(length=15), nullable=False),
            sa.Column("email", sa.String(length=100), nullable=False),
            sa.Column("hashed_password", sa.String(), nullable=False),
            sa.Column("security_question", sa.String(length=255), nullable=True),
            sa.Column("security_answer_hash", sa.String(), nullable=True),
            sa.Column("reporting_officer_id", sa.Integer(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["division_id"], ["divisions.id"]),
            sa.ForeignKeyConstraint(["zone_id"], ["zones.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email"),
            sa.UniqueConstraint("employee_id"),
        )
    else:
        existing_columns = {col["name"] for col in inspector.get_columns("users")}
        if "security_question" not in existing_columns:
            op.add_column("users", sa.Column("security_question", sa.String(length=255), nullable=True))
        if "security_answer_hash" not in existing_columns:
            op.add_column("users", sa.Column("security_answer_hash", sa.String(), nullable=True))

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("users")}
    indexes = [
        ("ix_users_id", ["id"]),
        ("ix_users_employee_id", ["employee_id"]),
    ]
    for name, columns in indexes:
        if name not in existing_indexes:
            op.create_index(name, "users", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("users"):
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("users")}
    if "ix_users_employee_id" in existing_indexes:
        op.drop_index(op.f("ix_users_employee_id"), table_name="users")
    if "ix_users_id" in existing_indexes:
        op.drop_index(op.f("ix_users_id"), table_name="users")

    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    if "security_answer_hash" in existing_columns:
        op.drop_column("users", "security_answer_hash")
    if "security_question" in existing_columns:
        op.drop_column("users", "security_question")
