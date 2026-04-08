"""
Unit tests for security utilities (password hashing, JWT creation/decoding).
"""

import pytest
from fastapi import HTTPException

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


# ── Password hashing ──────────────────────────────────────────────────────────


def test_hash_password_returns_non_empty_string():
    hashed = hash_password("mysecretpassword")
    assert isinstance(hashed, str)
    assert len(hashed) > 0


def test_hash_password_is_not_plaintext():
    plain = "mysecretpassword"
    hashed = hash_password(plain)
    assert hashed != plain


def test_verify_password_correct():
    plain = "correcthorsebatterystaple"
    hashed = hash_password(plain)
    assert verify_password(plain, hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("correctpassword")
    assert verify_password("wrongpassword", hashed) is False


def test_hash_same_password_produces_different_hashes():
    """bcrypt uses random salt — two hashes of the same input must differ."""
    plain = "samepassword"
    hash1 = hash_password(plain)
    hash2 = hash_password(plain)
    assert hash1 != hash2
    # But both must still verify correctly
    assert verify_password(plain, hash1) is True
    assert verify_password(plain, hash2) is True


# ── JWT ───────────────────────────────────────────────────────────────────────


def test_create_access_token_returns_string():
    settings = get_settings()
    token = create_access_token("user-123", settings=settings)
    assert isinstance(token, str)
    assert len(token) > 0


def test_decode_access_token_valid():
    settings = get_settings()
    subject = "user-42"
    token = create_access_token(subject, settings=settings)
    payload = decode_access_token(token, settings)

    assert payload["sub"] == subject
    assert "exp" in payload
    assert "iat" in payload


def test_decode_access_token_invalid_raises_http_exception():
    settings = get_settings()
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token("this.is.not.a.valid.jwt", settings)
    assert exc_info.value.status_code == 401


def test_decode_access_token_tampered_raises_http_exception():
    settings = get_settings()
    token = create_access_token("user-99", settings=settings)
    # Corrupt the signature part
    parts = token.split(".")
    tampered = parts[0] + "." + parts[1] + ".invalidsignature"
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(tampered, settings)
    assert exc_info.value.status_code == 401
