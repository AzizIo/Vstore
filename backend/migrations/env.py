import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db import payments as _payment_models  # noqa: F401
from app.db.models import Base
from scripts.e2e_safety import assert_e2e_environment
from scripts.preview_safety import should_validate_preview_migrations, validate_preview_targets

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Explicit opt-in guard for the isolated API-backed E2E migration path.
if os.getenv("E2E_MODE") == "1":
    asyncio.run(assert_e2e_environment())

# A Preview target must never bypass its guard by omitting PREVIEW_MODE.
# Also reject any explicitly supplied but invalid opt-in value.
settings = get_settings()
preview_mode = os.getenv("PREVIEW_MODE")
if should_validate_preview_migrations(settings.database_url, preview_mode):
    validate_preview_targets()
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
