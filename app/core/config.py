"""
Core configuration module.
Loads all settings from environment variables with sensible defaults.
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Application ─────────────────────────────────────────────────────────
    APP_NAME: str = "Ecommerce Invoice Sync API"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = (
        "Production-ready API that receives ecommerce orders "
        "and transforms them into invoices, syncing with an "
        "external billing system."
    )
    DEBUG: bool = False
    ALLOWED_HOSTS: List[str] = ["*"]

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/invoice_sync"
    )
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30

    # ── Security ─────────────────────────────────────────────────────────────
    SECRET_KEY: str = "change-me-in-production-at-least-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Static API key for machine-to-machine integrations (B2B clients)
    API_KEY_NAME: str = "X-API-Key"
    API_KEY: str = "ryzzAPIT3st"

    # ── External Billing System ───────────────────────────────────────────────
    BILLING_SYSTEM_URL: str = "https://billing.example.com/api/v1"
    BILLING_SYSTEM_API_KEY: str = "external-billing-key"
    BILLING_SYSTEM_TIMEOUT: int = 10  # seconds
    # Set to True in development/test to skip real HTTP calls and return a
    # simulated external ID instead of raising BillingSystemError on failure.
    BILLING_SYSTEM_MOCK: bool = False

    # ── Email (Resend) ────────────────────────────────────────────────────────
    RESEND_API_KEY: str = "re_placeholder"
    EMAIL_FROM: str = "facturas@tudominio.com"
    # Set True in development/test to skip real email delivery (just logs).
    EMAIL_MOCK: bool = True

    # ── Webhooks ──────────────────────────────────────────────────────────────
    # If empty, no webhook is dispatched.
    WEBHOOK_URL: str = ""
    WEBHOOK_SECRET: str = "change-me-webhook-secret"
    # Set True in development/test to skip the real HTTP POST (just logs).
    WEBHOOK_MOCK: bool = True

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False  # Set True in production for structured logging


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — loaded once per process."""
    return Settings()
