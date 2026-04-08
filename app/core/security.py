"""
Security module: API Key validation and JWT token utilities.

Supports two authentication strategies:
  1. Static API Key  (X-API-Key header)  — for B2B machine-to-machine calls.
  2. JWT Bearer token                    — for user-facing clients.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# ── Password hashing ──────────────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT utilities ─────────────────────────────────────────────────────────────
def create_access_token(
    subject: str | Any,
    settings: Settings = Depends(get_settings),
    expires_delta: timedelta | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": str(subject), "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate JWT token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ── API Key auth ──────────────────────────────────────────────────────────────
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(
    api_key: str | None = Security(_api_key_header),
    settings: Settings = Depends(get_settings),
) -> str:
    """FastAPI dependency — raises 403 if API key is missing or invalid."""
    if not api_key or api_key != settings.API_KEY:
        logger.warning("Rejected request: invalid or missing API key.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key.",
        )
    return api_key


# ── JWT Bearer auth ───────────────────────────────────────────────────────────
_bearer_scheme = HTTPBearer(auto_error=False)


def require_jwt(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> dict:
    """FastAPI dependency — raises 401 if bearer token is missing or invalid."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_access_token(credentials.credentials, settings)
