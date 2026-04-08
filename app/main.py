"""
Application entry point.

Registers routers, configures middleware, global exception handlers,
and lifecycle events (startup / shutdown).
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import get_settings
from app.core.limiter import limiter
from app.db.database import check_db_connection
from app.routers import invoices, orders

settings = get_settings()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    logger.info("Starting up %s v%s …", settings.APP_NAME, settings.APP_VERSION)
    # Database schema is managed by Alembic migrations.
    # Run `alembic upgrade head` before starting the application.
    db_ok = await check_db_connection()
    if not db_ok:
        logger.critical("Database is NOT reachable. Check DATABASE_URL.")
    else:
        logger.info("Database connection verified ✓")
    yield
    logger.info("Shutting down %s.", settings.APP_NAME)


# ── App factory ────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Attach the limiter to the app state so slowapi middleware can find it.
app.state.limiter = limiter

# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_HOSTS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Log every incoming request with method, path, status code, and duration."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s → %d  (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


# ── Global exception handlers ─────────────────────────────────────────────────
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_server_error",
            "detail": "An unexpected error occurred. Please try again later.",
        },
    )


# ── Routers ────────────────────────────────────────────────────────────────────
API_PREFIX = "/api/v1"

app.include_router(orders.router, prefix=API_PREFIX)
app.include_router(invoices.router, prefix=API_PREFIX)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"], summary="Health check")
async def health_check() -> dict:
    db_ok = await check_db_connection()
    return {
        "status": "healthy" if db_ok else "degraded",
        "version": settings.APP_VERSION,
        "database": "connected" if db_ok else "unreachable",
    }


@app.get("/", tags=["System"], include_in_schema=False)
async def root() -> dict:
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }
