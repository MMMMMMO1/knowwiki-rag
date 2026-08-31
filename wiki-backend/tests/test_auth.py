import time
import asyncio
import pytest
from fastapi import HTTPException
from app.models import User
from app.core.config import Settings
from app.core.security import (
    get_password_hash,
    verify_password,
    base64url_encode,
    base64url_decode,
    create_access_token,
    decode_access_token,
    require_roles,
)


def test_password_hashing_and_verification() -> None:
    password = "MySecurePassword123"
    hashed = get_password_hash(password)
    
    assert hashed != password
    assert ":" in hashed
    
    # Test valid verification
    assert verify_password(password, hashed) is True
    
    # Test invalid verification
    assert verify_password("WrongPassword", hashed) is False
    assert verify_password(password, "WrongHashedString") is False


def test_base64url_encoding_decoding() -> None:
    original = b"Hello, World! \xff\x00\x12"
    encoded = base64url_encode(original)
    
    # Base64url should not have padding '=' or URL unsafe characters like '+' or '/'
    assert "=" not in encoded
    assert "+" not in encoded
    assert "/" not in encoded
    
    decoded = base64url_decode(encoded)
    assert decoded == original


def test_jwt_token_flow() -> None:
    data = {"sub": "testuser", "role": "admin", "test": "value"}
    token = create_access_token(data)
    
    assert isinstance(token, str)
    assert len(token.split('.')) == 3
    
    # Test decode
    decoded = decode_access_token(token)
    assert decoded["sub"] == "testuser"
    assert decoded["role"] == "admin"
    assert decoded["test"] == "value"
    assert "exp" in decoded


def test_jwt_invalid_signature() -> None:
    data = {"sub": "testuser"}
    token = create_access_token(data)
    
    # Modify token to invalidate signature
    parts = token.split('.')
    parts[2] = parts[2] + "invalid"
    invalid_token = ".".join(parts)
    
    with pytest.raises(ValueError, match="Signature verification failed"):
        decode_access_token(invalid_token)


def test_jwt_expiration() -> None:
    from datetime import timedelta
    data = {"sub": "testuser"}
    
    # Create expired token
    token = create_access_token(data, expires_delta=timedelta(seconds=-10))
    
    with pytest.raises(ValueError, match="Token expired"):
        decode_access_token(token)


def _security_settings(**overrides) -> Settings:
    values = {
        "DB_PASSWORD": "database-secret",
        "S3_ACCESS_KEY": "storage-user",
        "S3_SECRET_KEY": "storage-secret",
        "JWT_SECRET": "a-secure-jwt-secret-that-is-long-enough",
        "ADMIN_PASSWORD": "a-secure-admin-password",
        "CORS_ORIGINS": ["https://wiki.example.com"],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_runtime_security_rejects_missing_credentials() -> None:
    config = _security_settings(DB_PASSWORD="")
    with pytest.raises(RuntimeError, match="DB_PASSWORD"):
        config.validate_runtime_security()


def test_runtime_security_rejects_production_defaults() -> None:
    config = _security_settings(
        ENVIRONMENT="production",
        ADMIN_PASSWORD="admin123",
    )
    with pytest.raises(RuntimeError, match="默认或占位凭证"):
        config.validate_runtime_security()


def test_runtime_security_accepts_strong_production_configuration() -> None:
    _security_settings(ENVIRONMENT="production").validate_runtime_security()


def test_admin_only_dependency_rejects_editor() -> None:
    dependency = require_roles("admin")
    editor = User(id=2, username="editor", role="editor", is_active=True)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(dependency(editor))
    assert exc_info.value.status_code == 403
