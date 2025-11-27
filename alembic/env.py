import os
import asyncio
from logging.config import fileConfig
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context
from app.database import Base  # Import your Base model

# Alembic Config object, provides access to the .ini file values
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Database URL from environment or default to SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///raffle.db")

# Metadata for Alembic autogenerate
target_metadata = Base.metadata

# ----------------------------------------------------------------------
# Run migrations offline
# ----------------------------------------------------------------------
def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

# ----------------------------------------------------------------------
# Run migrations online (async)
# ----------------------------------------------------------------------
def run_migrations_online():
    """Run migrations in 'online' mode with async engine."""

    connectable = create_async_engine(DATABASE_URL, echo=True, future=True)

    async def do_run_migrations():
        async with connectable.begin() as connection:
            await connection.run_sync(run_migrations)

    async def run_migrations(connection):
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()

    asyncio.run(do_run_migrations())

# ----------------------------------------------------------------------
# Choose offline or online mode
# ----------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
