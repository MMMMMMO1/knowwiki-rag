import base64
import hmac
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app import models

# HTTP Bearer token security scheme
security = HTTPBearer(auto_error=False)
VALID_USER_ROLES = {"admin", "editor", "reader"}
ADMIN_EDITOR_ROLES = {"admin", "editor"}

# Password hashing utilities using standard library PBKDF2
def get_password_hash(password: str) -> str:
    # Generate a random 16-byte salt
    salt = secrets.token_hex(16)
    # Hash password using PBKDF2 with SHA-256 and 100,000 iterations
    hashed = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    # Store salt and hash separated by a colon
    return f"{salt}:{hashed.hex()}"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        salt, stored_hash = hashed_password.split(':')
        calc_hash = hashlib.pbkdf2_hmac(
            'sha256',
            plain_password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return secrets.compare_digest(calc_hash.hex(), stored_hash)
    except Exception:
        return False

# JWT utilities using standard library (No external dependencies)
JWT_SECRET_KEY = settings.JWT_SECRET
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 day

def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')

def base64url_decode(data: str) -> bytes:
    padding = '=' * (4 - (len(data) % 4))
    return base64.urlsafe_b64decode((data + padding).encode('utf-8'))

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # 说明：iat 用于后续审计和排查旧 Token；权限仍以数据库用户状态为准。
    now = datetime.now(timezone.utc)
    to_encode.update({"exp": int(expire.timestamp()), "iat": int(now.timestamp())})
    
    header = {"alg": ALGORITHM, "typ": "JWT"}
    header_b64 = base64url_encode(json.dumps(header).encode('utf-8'))
    payload_b64 = base64url_encode(json.dumps(to_encode).encode('utf-8'))
    
    signing_input = f"{header_b64}.{payload_b64}".encode('utf-8')
    signature = hmac.new(JWT_SECRET_KEY.encode('utf-8'), signing_input, hashlib.sha256).digest()
    signature_b64 = base64url_encode(signature)
    
    return f"{header_b64}.{payload_b64}.{signature_b64}"

def decode_access_token(token: str) -> dict:
    try:
        parts = token.split('.')
        if len(parts) != 3:
            raise ValueError("Invalid token format")
        
        header_b64, payload_b64, signature_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode('utf-8')

        header_json = base64url_decode(header_b64).decode('utf-8')
        header = json.loads(header_json)
        if header.get("alg") != ALGORITHM or header.get("typ") != "JWT":
            raise ValueError("Unsupported token header")
        
        # Verify signature
        calc_sig = hmac.new(JWT_SECRET_KEY.encode('utf-8'), signing_input, hashlib.sha256).digest()
        expected_sig_b64 = base64url_encode(calc_sig)
        
        if not hmac.compare_digest(signature_b64, expected_sig_b64):
            raise ValueError("Signature verification failed")
        
        # Decode payload
        payload_json = base64url_decode(payload_b64).decode('utf-8')
        payload = json.loads(payload_json)
        
        # Verify expiration
        if "exp" in payload:
            exp = payload["exp"]
            if datetime.now(timezone.utc).timestamp() > exp:
                raise ValueError("Token expired")
                
        return payload
    except Exception as e:
        raise ValueError(f"Invalid token: {str(e)}")

def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


# Dependency to resolve user profile from token
async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> models.User:
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Authentication credentials were not provided")

    token = credentials.credentials
    
    try:
        payload = decode_access_token(token)
        username = payload.get("sub")
        if not isinstance(username, str) or not username.strip():
            raise _unauthorized("Token does not contain user identification")
    except ValueError as e:
        raise _unauthorized(f"Could not validate credentials: {str(e)}")
        
    result = await db.execute(select(models.User).filter(models.User.username == username))
    user = result.scalars().first()
    if user is None:
        raise _unauthorized("User not found")
    if not user.is_active:
        raise _unauthorized("User is inactive")
    if user.role not in VALID_USER_ROLES:
        raise _forbidden("User role is not allowed")
    return user

def require_roles(*allowed_roles: str):
    async def dependency(
        current_user: models.User = Depends(get_current_user),
    ) -> models.User:
        # 说明：权限判断只读取数据库中的当前角色，不再信任 JWT payload 中可能过期的 role 字段。
        if current_user.role not in allowed_roles:
            allowed = ", ".join(sorted(allowed_roles))
            raise _forbidden(f"Only {allowed} role can access this resource")
        return current_user

    return dependency


require_admin_or_editor = require_roles(*ADMIN_EDITOR_ROLES)


async def verify_admin_token(
    current_user: models.User = Depends(require_admin_or_editor),
) -> models.User:
    """
    Backward-compatible dependency name for admin/editor JWT authentication.

    说明：这里不再校验任何静态 ADMIN_TOKEN，只校验数据库用户签发的 JWT。
    """
    return current_user
