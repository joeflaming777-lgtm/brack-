"""
AuditLog model.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
import enum

from sqlalchemy import String, DateTime, Text, ForeignKey, Enum as SAEnum, Uuid, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditEventType(str, enum.Enum):
    # Auth
    USER_REGISTERED = "user.registered"
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    USER_LOGIN_FAILED = "user.login_failed"
    # Tokens
    TOKEN_CREATED = "token.created"
    TOKEN_REVOKED = "token.revoked"
    # Repos
    REPO_CREATED = "repo.created"
    REPO_DELETED = "repo.deleted"
    REPO_UPDATED = "repo.updated"
    REPO_VISIBILITY_CHANGED = "repo.visibility_changed"
    # Git
    GIT_PUSH = "git.push"
    GIT_CLONE = "git.clone"
    GIT_PULL = "git.pull"
    # SSH
    SSH_KEY_ADDED = "ssh_key.added"
    SSH_KEY_REMOVED = "ssh_key.removed"
    # Security
    SECURITY_ALERT = "security.alert"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    user: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<AuditLog {self.event_type} by {self.user_id}>"
