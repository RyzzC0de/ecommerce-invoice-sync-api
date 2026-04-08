"""
Root conftest.py — shared fixtures and pytest configuration.

Overrides:
  - DATABASE_URL → sqlite+aiosqlite:///./test.db  (no PostgreSQL required)
  - API_KEY     → test-api-key
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── 1. Override env vars BEFORE any app code is imported ──────────────────────
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["API_KEY"] = "test-api-key"
os.environ["BILLING_SYSTEM_MOCK"] = "true"  # no real HTTP calls in tests
os.environ["EMAIL_MOCK"] = "true"           # no real emails in tests
os.environ["WEBHOOK_MOCK"] = "true"         # no real webhooks in tests

# ── 2. Patch PostgreSQL UUID column type to work with SQLite ──────────────────
# Must happen before models are imported (Base.metadata is populated).
from sqlalchemy.dialects.postgresql import UUID as PG_UUID  # noqa: E402

_original_pg_uuid_init = PG_UUID.__init__


def _patched_pg_uuid_init(self, as_uuid=False):
    """Override the PostgreSQL UUID type to use a plain String(32) on SQLite."""
    _original_pg_uuid_init(self, as_uuid=as_uuid)


# We override how the UUID column compiles on the SQLite dialect.
from sqlalchemy.dialects import sqlite as sqlite_dialect  # noqa: E402

# Register a visit rule so the SQLite compiler renders UUID as CHAR(32)
from sqlalchemy.sql import compiler  # noqa: E402


from sqlalchemy import TypeDecorator  # noqa: E402
import uuid as _uuid_mod  # noqa: E402


class SQLiteUUID(TypeDecorator):
    """Platform-independent UUID type: stores as CHAR(32) on SQLite."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, _uuid_mod.UUID):
                return value.hex
            return _uuid_mod.UUID(value).hex
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return _uuid_mod.UUID(value)
        return value


# Monkey-patch so that when PG_UUID columns are compiled against SQLite,
# they use a string column instead.
import sqlalchemy.dialects.postgresql as pg_mod  # noqa: E402

_OrigUUID = pg_mod.UUID


class _PatchedUUID(_OrigUUID):
    """UUID that falls back to CHAR(32) on non-PostgreSQL dialects."""

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(32))
        return super().load_dialect_impl(dialect)

    def process_bind_param(self, value, dialect):
        if dialect.name == "sqlite" and value is not None:
            if isinstance(value, _uuid_mod.UUID):
                return value.hex
            return _uuid_mod.UUID(str(value)).hex
        return value

    def process_result_value(self, value, dialect):
        if dialect.name == "sqlite" and value is not None:
            if not isinstance(value, _uuid_mod.UUID):
                return _uuid_mod.UUID(value)
        return value


pg_mod.UUID = _PatchedUUID

# ── 3. Now import app code (models will use the patched UUID) ─────────────────
from app.core.config import get_settings  # noqa: E402
from app.core.limiter import limiter  # noqa: E402
from app.db.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

# ── 4. Reset the cached settings so the overrides take effect ─────────────────
get_settings.cache_clear()

# Disable rate limiting so tests are not throttled.
limiter.enabled = False


# ── 5. Test engine (SQLite, no pool options) ──────────────────────────────────
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# ── 6. Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def anyio_backend():
    """Force anyio / pytest-asyncio to use asyncio."""
    return "asyncio"


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """Create all tables before each test, drop them after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency override that uses the test SQLite database."""
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Apply the override globally
app.dependency_overrides[get_db] = _override_get_db


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client wired to the FastAPI app (no network needed)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── 7. Auto-mock heavyweight/external service dependencies ────────────────────
#
# PDFService uses WeasyPrint (requires system Cairo/Pango libraries).
# EmailService calls the Resend API over the network.
# WebhookService makes outbound HTTP POSTs.
#
# All three are mocked globally so no system library or network access is
# needed during any test in the suite.  Individual test modules may override
# these patches for targeted behaviour testing.


@pytest.fixture(autouse=True)
def mock_pdf_service():
    """Replace PDFService.generate_invoice_pdf with a stub returning fake bytes."""
    with patch(
        "app.services.invoice_service.PDFService.generate_invoice_pdf",
        return_value=b"%PDF-1.4 fake-pdf-content",
    ) as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_email_service():
    """Replace EmailService.send_invoice with a no-op coroutine."""
    with patch(
        "app.services.invoice_service.EmailService.send_invoice",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_webhook_service():
    """Replace WebhookService.dispatch with a no-op coroutine."""
    with patch(
        "app.services.invoice_service.WebhookService.dispatch",
        new_callable=AsyncMock,
    ) as mock:
        yield mock
