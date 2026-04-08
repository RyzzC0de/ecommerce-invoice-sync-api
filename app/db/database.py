"""
Database module: async SQLAlchemy engine, session factory, and base model.
"""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Engine ────────────────────────────────────────────────────────────────────
# Pool options are only valid for PostgreSQL (asyncpg). SQLite (aiosqlite),
# used in tests, does not support them.
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
_engine_kwargs: dict = {"echo": settings.DEBUG, "pool_pre_ping": not _is_sqlite}
if not _is_sqlite:
    _engine_kwargs.update(
        {
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
            "pool_timeout": settings.DB_POOL_TIMEOUT,
        }
    )
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)


# ── Session factory ───────────────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# ── Declarative base ──────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """All ORM models inherit from this base."""
    pass


# ── FastAPI dependency ────────────────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an async database session.
    Rolls back on unhandled exceptions, always closes the session.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Lifecycle helpers ─────────────────────────────────────────────────────────
async def init_db() -> None:
    """Create all tables (idempotent). Called on application startup."""
    async with engine.begin() as conn:
        # Import models so Base.metadata is populated before create_all
        from app.models import invoice, order  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created / verified.")


async def check_db_connection() -> bool:
    """Health-check helper — returns True if DB is reachable."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("DB health check failed: %s", exc)
        return False
