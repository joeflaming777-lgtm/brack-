"""
Authentication API routes.
"""
from datetime import timedelta
from typing import List

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.auth.dependencies import CurrentUser, DBSession
from app.config.settings import get_settings
from app.models.user import AccessToken
from app.schemas.auth import (
    RegisterRequest, LoginRequest, TokenResponse, UserResponse, UserUpdateRequest
)
from app.schemas.repository import TokenCreateRequest, TokenCreateResponse, TokenListItem
from app.services.auth_service import AuthService


router = APIRouter(prefix="/auth", tags=["Authentication"])
settings = get_settings()


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(body: RegisterRequest, request: Request, db: DBSession):
    """Register a new user account."""
    svc = AuthService(db)
    try:
        user = await svc.register(
            username=body.username,
            email=str(body.email),
            password=body.password,
            display_name=body.display_name,
            ip_address=request.client.host if request.client else None,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return user


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, response: Response, db: DBSession):
    """Authenticate and receive a JWT token."""
    svc = AuthService(db)
    try:
        user, token = await svc.login(
            username_or_email=body.username,
            password=body.password,
            ip_address=request.client.host if request.client else None,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )

    # Set httpOnly cookie
    response.set_cookie(
        key="brack_token",
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.BRACK_JWT_EXPIRE_MINUTES * 60,
        path="/",
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.BRACK_JWT_EXPIRE_MINUTES * 60,
    )


@router.post("/logout")
async def logout(response: Response):
    """Clear authentication cookie."""
    response.delete_cookie("brack_token", path="/")
    return {"message": "Logged out successfully."}


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser):
    """Get the currently authenticated user."""
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_me(body: UserUpdateRequest, current_user: CurrentUser, db: DBSession):
    """Update current user profile."""
    if body.display_name is not None:
        current_user.display_name = body.display_name
    if body.bio is not None:
        current_user.bio = body.bio
    if body.avatar_url is not None:
        current_user.avatar_url = body.avatar_url
    await db.commit()
    await db.refresh(current_user)
    return current_user


# ── Personal Access Tokens ────────────────────────────────────────────────────

@router.post("/tokens", response_model=TokenCreateResponse, status_code=201)
async def create_token(
    body: TokenCreateRequest, current_user: CurrentUser, db: DBSession
):
    """Create a Personal Access Token."""
    svc = AuthService(db)
    pat, raw_token = await svc.create_access_token(
        user=current_user,
        name=body.name,
        scopes=body.scopes,
        expires_days=body.expires_days,
    )
    return TokenCreateResponse(
        id=pat.id,
        name=pat.name,
        token=raw_token,
        prefix=pat.token_prefix,
        scopes=pat.scopes_list,
        created_at=pat.created_at,
        expires_at=pat.expires_at,
    )


@router.get("/tokens", response_model=List[TokenListItem])
async def list_tokens(current_user: CurrentUser, db: DBSession):
    """List all Personal Access Tokens for the current user."""
    svc = AuthService(db)
    tokens = await svc.list_access_tokens(current_user)
    return [
        TokenListItem(
            id=t.id,
            name=t.name,
            prefix=t.token_prefix,
            scopes=t.scopes_list,
            last_used_at=t.last_used_at,
            created_at=t.created_at,
            expires_at=t.expires_at,
        )
        for t in tokens
    ]


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(token_id: str, current_user: CurrentUser, db: DBSession):
    """Revoke a Personal Access Token."""
    import uuid as _uuid
    try:
        tid = _uuid.UUID(token_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid token ID.")
    svc = AuthService(db)
    try:
        await svc.revoke_access_token(current_user, tid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
