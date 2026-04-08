"""
Alembic environment configuration for async SQLAlchemy (asyncpg driver).

DATABASE_URL is taken directly from app.core.config so it always matches
what the application itself uses — no duplication of connection strings.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Load app settings (and therefore DATABASE_URL) ────────────────────────────
from app.core.config import get_settings

# ── Import Base.metadata + ALL models so Alembic sees every table ─────────────
from app.db.database import Base
from app.models import invoice, order  # noqa: F401  — registers ORM metadata

# ── Alembic Config object ─────────────────────────────────────────────────────
config = context.config

# Override the sqlalchemy.url with the value from our Settings object.
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Interpret the config file for Python logging if present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata object for 'autogenerate' support.
target_metadata = Base.metadata


# ── Offline migrations (no live DB connection needed) ─────────────────────────
def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DB connection (useful for review/CI)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (async) ─────────────────────────────────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations within it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migration mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
