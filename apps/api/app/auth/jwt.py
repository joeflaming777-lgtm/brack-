"""
JWT creation and verification.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from pydantic import BaseModel

from app.config.settings import get_settings


class TokenData(BaseModel):
    sub: str  # user ID (UUID as string)
    username: str
    is_admin: bool = False
    token_type: str = "access"  # "access" or "refresh"


def create_access_token(
    user_id: uuid.UUID,
    username: str,
    is_admin: bool = False,
    expires_delta: Optional[timedelta] = None,
) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.BRACK_JWT_EXPIRE_MINUTES)
    )
    payload = {
        "sub": str(user_id),
        "username": username,
        "is_admin": is_admin,
        "token_type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(
        payload,
        settings.BRACK_JWT_SECRET,
        algorithm=settings.BRACK_JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> Optional[TokenData]:
    """Decode and validate a JWT. Returns None if invalid."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.BRACK_JWT_SECRET,
            algorithms=[settings.BRACK_JWT_ALGORITHM],
        )
        if payload.get("token_type") != "access":
            return None
        return TokenData(
            sub=payload["sub"],
            username=payload["username"],
            is_admin=payload.get("is_admin", False),
        )
    except JWTError:
        return None
