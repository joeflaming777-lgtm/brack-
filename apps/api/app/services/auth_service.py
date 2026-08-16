"""
Authentication service — register, login, token management.
"""
import uuid
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.models.user import User, AccessToken
from app.models.audit import AuditLog, AuditEventType
from app.auth.password import hash_password, verify_password
from app.auth.jwt import create_access_token
from app.config.settings import get_settings


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    async def register(
        self,
        username: str,
        email: str,
        password: str,
        display_name: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> User:
        """Register a new user. Raises ValueError on conflict."""

        # Check if registration is allowed
        if not self.settings.BRACK_ALLOW_REGISTRATION:
            raise PermissionError("Registration is currently disabled.")

        # Check username / email uniqueness
        existing = await self.db.execute(
            select(User).where(or_(User.username == username, User.email == email))
        )
        if existing.scalar_one_or_none():
            raise ValueError("Username or email already taken.")

        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            display_name=display_name or username,
        )
        self.db.add(user)
        await self.db.flush()  # get user.id

        await self._audit(
            user_id=user.id,
            event_type=AuditEventType.USER_REGISTERED,
            ip_address=ip_address,
        )
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def login(
        self,
        username_or_email: str,
        password: str,
        ip_address: Optional[str] = None,
    ) -> tuple[User, str]:
        """
        Authenticate user. Returns (user, jwt_token).
        Raises ValueError on bad credentials.
        """
        result = await self.db.execute(
            select(User).where(
                or_(
                    User.username == username_or_email.lower(),
                    User.email == username_or_email.lower(),
                )
            )
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(password, user.password_hash):
            await self._audit(
                event_type=AuditEventType.USER_LOGIN_FAILED,
                ip_address=ip_address,
                metadata={"attempted_username": username_or_email},
            )
            await self.db.commit()
            raise ValueError("Invalid username or password.")

        if not user.is_active:
            raise ValueError("Account is disabled.")

        # Update last login
        user.last_login_at = datetime.now(timezone.utc)
        await self.db.flush()

        token = create_access_token(
            user_id=user.id,
            username=user.username,
            is_admin=user.is_admin,
        )

        await self._audit(
            user_id=user.id,
            event_type=AuditEventType.USER_LOGIN,
            ip_address=ip_address,
        )
        await self.db.commit()
        return user, token

    async def create_access_token(
        self,
        user: User,
        name: str,
        scopes: list[str],
        expires_days: Optional[int] = None,
    ) -> tuple[AccessToken, str]:
        """
        Create a Personal Access Token.
        Returns (token_db, raw_token) — raw_token shown only once.
        """
        raw = "brk_" + secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        prefix = raw[:12]  # "brk_" + first 8 chars

        expires_at = None
        if expires_days:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

        pat = AccessToken(
            user_id=user.id,
            name=name,
            token_hash=token_hash,
            token_prefix=prefix,
            scopes=" ".join(scopes),
            expires_at=expires_at,
        )
        self.db.add(pat)
        await self.db.flush()

        await self._audit(
            user_id=user.id,
            event_type=AuditEventType.TOKEN_CREATED,
            resource_id=str(pat.id),
            metadata={"name": name, "scopes": scopes},
        )
        await self.db.commit()
        await self.db.refresh(pat)
        return pat, raw

    async def revoke_access_token(self, user: User, token_id: uuid.UUID) -> None:
        """Revoke a PAT owned by user."""
        result = await self.db.execute(
            select(AccessToken).where(
                AccessToken.id == token_id,
                AccessToken.user_id == user.id,
            )
        )
        pat = result.scalar_one_or_none()
        if not pat:
            raise ValueError("Token not found.")

        pat.is_active = False
        await self._audit(
            user_id=user.id,
            event_type=AuditEventType.TOKEN_REVOKED,
            resource_id=str(pat.id),
        )
        await self.db.commit()

    async def list_access_tokens(self, user: User) -> list[AccessToken]:
        result = await self.db.execute(
            select(AccessToken).where(
                AccessToken.user_id == user.id,
                AccessToken.is_active == True,
            ).order_by(AccessToken.created_at.desc())
        )
        return list(result.scalars().all())

    async def _audit(
        self,
        event_type: str,
        user_id: Optional[uuid.UUID] = None,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        log = AuditLog(
            user_id=user_id,
            event_type=event_type,
            resource_type="user",
            resource_id=resource_id,
            ip_address=ip_address,
            metadata_=metadata,
        )
        self.db.add(log)
