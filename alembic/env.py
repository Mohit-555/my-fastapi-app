from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from app.database import Base, engine
from app.models import models  # noqa

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata   # ← changed from None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:   # ← using app engine directly
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()