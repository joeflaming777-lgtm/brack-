"""
Repository, RepositoryMember models.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List
import enum

from sqlalchemy import (
    String, Boolean, DateTime, Text, ForeignKey,
    Enum as SAEnum, Integer, UniqueConstraint, Uuid
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RepoVisibility(str, enum.Enum):
    PUBLIC = "public"
    PRIVATE = "private"


class MemberRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    WRITE = "write"
    READ = "read"


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)  # URL-safe name
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    visibility: Mapped[RepoVisibility] = mapped_column(
        SAEnum(RepoVisibility), default=RepoVisibility.PRIVATE, nullable=False
    )
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    is_empty: Mapped[bool] = mapped_column(Boolean, default=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_fork: Mapped[bool] = mapped_column(Boolean, default=False)
    fork_of_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True
    )

    # Stats (cached, updated asynchronously)
    stars_count: Mapped[int] = mapped_column(Integer, default=0)
    forks_count: Mapped[int] = mapped_column(Integer, default=0)
    watchers_count: Mapped[int] = mapped_column(Integer, default=0)
    open_issues_count: Mapped[int] = mapped_column(Integer, default=0)

    # Git storage path (relative to BRACK_STORAGE_PATH)
    git_path: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)

    # Init options
    init_readme: Mapped[bool] = mapped_column(Boolean, default=False)
    gitignore_template: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    license_template: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_push_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="repositories")
    members: Mapped[List["RepositoryMember"]] = relationship(
        "RepositoryMember", back_populates="repository", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("owner_id", "slug", name="uq_repo_owner_slug"),
    )

    def __repr__(self) -> str:
        return f"<Repository {self.owner_id}/{self.slug}>"


class RepositoryMember(Base):
    __tablename__ = "repository_members"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    role: Mapped[MemberRole] = mapped_column(
        SAEnum(MemberRole), default=MemberRole.READ, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Relationships
    repository: Mapped["Repository"] = relationship("Repository", back_populates="members")
    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        UniqueConstraint("repository_id", "user_id", name="uq_repo_member"),
    )
