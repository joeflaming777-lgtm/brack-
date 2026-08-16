"""
FastAPI dependencies for authentication and authorization.
"""
import hashlib
import uuid
from typing import Optional, Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.auth.jwt import decode_access_token
from app.database import get_db
from app.models.user import User, AccessToken


security = HTTPBearer(auto_error=False)


async def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Try to authenticate from:
    1. Bearer token (JWT or Personal Access Token)
    2. Cookie (brack_token)
    Returns None if not authenticated.
    """
    token: Optional[str] = None

    # 1. Bearer header
    if credentials and credentials.credentials:
        token = credentials.credentials

    # 2. Cookie fallback
    if not token:
        token = request.cookies.get("brack_token")

    if not token:
        return None

    # Try JWT first
    token_data = decode_access_token(token)
    if token_data:
        result = await db.execute(
            select(User).where(User.id == uuid.UUID(token_data.sub), User.is_active == True)
        )
        return result.scalar_one_or_none()

    # Try Personal Access Token (prefix "brk_")
    if token.startswith("brk_"):
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        result = await db.execute(
            select(AccessToken).where(
                AccessToken.token_hash == token_hash,
                AccessToken.is_active == True,
            )
        )
        pat = result.scalar_one_or_none()
        if pat:
            # Load the user
            user_result = await db.execute(
                select(User).where(User.id == pat.user_id, User.is_active == True)
            )
            return user_result.scalar_one_or_none()

    return None


async def get_current_user(
    user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    """Require authentication — raises 401 if not authenticated."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Require admin privileges."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required.",
        )
    return user


# Convenient type aliases
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[Optional[User], Depends(get_current_user_optional)]
AdminUser = Annotated[User, Depends(get_current_admin)]
DBSession = Annotated[AsyncSession, Depends(get_db)]
