"""add rbac menus roles role_menus user_role_id

Revision ID: e8eb8e29ee31
Revises: 2c9e7b1a5d03
Create Date: 2026-06-08 06:39:40.941303

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8eb8e29ee31'
down_revision: Union[str, None] = '2c9e7b1a5d03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("menus"):
        op.create_table(
            "menus",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("slug", sa.String(length=100), nullable=False),
            sa.Column("parent_slug", sa.String(length=100), nullable=True),
            sa.Column("icon", sa.String(length=50), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )
        op.create_index(op.f("ix_menus_id"), "menus", ["id"], unique=False)

    if not inspector.has_table("roles"):
        op.create_table(
            "roles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=50), nullable=False),
            sa.Column("display_name", sa.String(length=100), nullable=False),
            sa.Column("level", sa.Integer(), nullable=False),
            sa.Column("description", sa.String(length=200), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
        op.create_index(op.f("ix_roles_id"), "roles", ["id"], unique=False)

    if not inspector.has_table("role_menus"):
        op.create_table(
            "role_menus",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("role_id", sa.Integer(), nullable=False),
            sa.Column("menu_id", sa.Integer(), nullable=False),
            sa.Column("permission", sa.String(length=20), nullable=False),
            sa.ForeignKeyConstraint(["menu_id"], ["menus.id"]),
            sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("role_id", "menu_id", name="uq_role_menu"),
        )
        op.create_index(op.f("ix_role_menus_id"), "role_menus", ["id"], unique=False)
        op.create_index(op.f("ix_role_menus_menu_id"), "role_menus", ["menu_id"], unique=False)
        op.create_index(op.f("ix_role_menus_role_id"), "role_menus", ["role_id"], unique=False)

    user_columns = {col["name"] for col in inspector.get_columns("users")}
    if "role_id" not in user_columns:
        op.add_column("users", sa.Column("role_id", sa.Integer(), nullable=True))

    user_indexes = {idx["name"] for idx in inspector.get_indexes("users")}
    if "ix_users_role_id" not in user_indexes:
        op.create_index(op.f("ix_users_role_id"), "users", ["role_id"], unique=False)

    user_foreign_keys = inspector.get_foreign_keys("users")
    has_role_fk = any(
        fk.get("constrained_columns") == ["role_id"] and fk.get("referred_table") == "roles"
        for fk in user_foreign_keys
    )
    if not has_role_fk:
        op.create_foreign_key("fk_users_role_id_roles", "users", "roles", ["role_id"], ["id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("users"):
        user_foreign_keys = inspector.get_foreign_keys("users")
        role_fk_names = [
            fk["name"]
            for fk in user_foreign_keys
            if fk.get("constrained_columns") == ["role_id"]
            and fk.get("referred_table") == "roles"
            and fk.get("name")
        ]
        for fk_name in role_fk_names:
            op.drop_constraint(fk_name, "users", type_="foreignkey")

        user_indexes = {idx["name"] for idx in inspector.get_indexes("users")}
        if "ix_users_role_id" in user_indexes:
            op.drop_index(op.f("ix_users_role_id"), table_name="users")

        user_columns = {col["name"] for col in inspector.get_columns("users")}
        if "role_id" in user_columns:
            op.drop_column("users", "role_id")

    if inspector.has_table("role_menus"):
        role_menu_indexes = {idx["name"] for idx in inspector.get_indexes("role_menus")}
        for index_name in ("ix_role_menus_role_id", "ix_role_menus_menu_id", "ix_role_menus_id"):
            if index_name in role_menu_indexes:
                op.drop_index(op.f(index_name), table_name="role_menus")
        op.drop_table("role_menus")

    if inspector.has_table("roles"):
        role_indexes = {idx["name"] for idx in inspector.get_indexes("roles")}
        if "ix_roles_id" in role_indexes:
            op.drop_index(op.f("ix_roles_id"), table_name="roles")
        op.drop_table("roles")

    if inspector.has_table("menus"):
        menu_indexes = {idx["name"] for idx in inspector.get_indexes("menus")}
        if "ix_menus_id" in menu_indexes:
            op.drop_index(op.f("ix_menus_id"), table_name="menus")
        op.drop_table("menus")
