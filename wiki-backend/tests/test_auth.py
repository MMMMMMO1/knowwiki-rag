import time
import pytest
from app.core.security import (
    get_password_hash,
    verify_password,
    base64url_encode,
    base64url_decode,
    create_access_token,
    decode_access_token,
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
