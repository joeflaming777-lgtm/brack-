"""
Repository service — create, delete, list repositories.
Manages bare Git repositories on disk.
"""
import uuid
import os
import shutil
from typing import Optional, List
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload

from app.models.repository import Repository, RepositoryMember, RepoVisibility, MemberRole
from app.models.user import User
from app.models.audit import AuditLog, AuditEventType
from app.config.settings import get_settings
from app.git.operations import GitOperations


class RepoService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    def _repo_disk_path(self, username: str, slug: str) -> str:
        """Absolute path to the bare Git repository on disk."""
        base = os.path.abspath(self.settings.BRACK_STORAGE_PATH)
        # Security: sanitize username and slug
        safe_user = self._safe_path_segment(username)
        safe_slug = self._safe_path_segment(slug)
        return os.path.join(base, safe_user, f"{safe_slug}.git")

    @staticmethod
    def _safe_path_segment(segment: str) -> str:
        """Remove any path traversal characters."""
        import re
        clean = re.sub(r"[^a-zA-Z0-9_\-\.]", "", segment)
        if not clean or clean.startswith("."):
            raise ValueError(f"Invalid path segment: {segment!r}")
        return clean

    async def create_repo(
        self,
        owner: User,
        name: str,
        description: Optional[str] = None,
        visibility: RepoVisibility = RepoVisibility.PRIVATE,
        init_readme: bool = False,
        gitignore_template: Optional[str] = None,
        license_template: Optional[str] = None,
        default_branch: str = "main",
    ) -> Repository:
        """Create a repository record and initialize a bare Git repo on disk."""
        slug = name.lower().replace(" ", "-")

        # Check uniqueness
        existing = await self.db.execute(
            select(Repository).where(
                Repository.owner_id == owner.id,
                Repository.slug == slug,
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Repository '{name}' already exists.")

        git_path = self._repo_disk_path(owner.username, slug)

        repo = Repository(
            owner_id=owner.id,
            name=name,
            slug=slug,
            description=description,
            visibility=visibility,
            default_branch=default_branch,
            is_empty=not init_readme,
            git_path=git_path,
            init_readme=init_readme,
            gitignore_template=gitignore_template,
            license_template=license_template,
        )
        self.db.add(repo)
        await self.db.flush()

        # Initialize the bare repo on disk
        git_ops = GitOperations(git_path)
        git_ops.init_bare(
            default_branch=default_branch,
            init_readme=init_readme,
            repo_name=name,
            description=description,
        )

        if init_readme:
            repo.is_empty = False

        await self._audit(
            user_id=owner.id,
            event_type=AuditEventType.REPO_CREATED,
            resource_id=str(repo.id),
            metadata={"name": name, "visibility": visibility.value},
        )
        await self.db.commit()
        await self.db.refresh(repo, ["owner"])
        return repo

    async def get_repo(
        self,
        owner_username: str,
        repo_slug: str,
        requesting_user: Optional[User] = None,
    ) -> Optional[Repository]:
        """Get a repository, checking access permissions."""
        result = await self.db.execute(
            select(Repository)
            .join(User, Repository.owner_id == User.id)
            .where(
                User.username == owner_username,
                Repository.slug == repo_slug.lower(),
            )
            .options(selectinload(Repository.owner))
        )
        repo = result.scalar_one_or_none()
        if not repo:
            return None

        # Access control
        if repo.visibility == RepoVisibility.PRIVATE:
            if not requesting_user:
                return None
            if repo.owner_id != requesting_user.id and not requesting_user.is_admin:
                # Check member access
                member = await self._get_member(repo.id, requesting_user.id)
                if not member:
                    return None

        return repo

    async def list_repos(
        self,
        owner: Optional[User] = None,
        requesting_user: Optional[User] = None,
        include_private: bool = False,
        page: int = 1,
        per_page: int = 30,
    ) -> tuple[List[Repository], int]:
        """List repositories for an owner with access control."""
        query = select(Repository).options(selectinload(Repository.owner))

        if owner:
            query = query.where(Repository.owner_id == owner.id)

        # Visibility filter
        if not include_private:
            if requesting_user and owner and requesting_user.id == owner.id:
                pass  # owner sees all their own repos
            else:
                query = query.where(Repository.visibility == RepoVisibility.PUBLIC)

        query = query.order_by(Repository.updated_at.desc())

        # Count
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0

        # Paginate
        query = query.offset((page - 1) * per_page).limit(per_page)
        result = await self.db.execute(query)
        repos = list(result.scalars().all())

        return repos, total

    async def delete_repo(self, repo: Repository, requesting_user: User) -> None:
        """Delete a repository — removes DB record and disk storage."""
        if repo.owner_id != requesting_user.id and not requesting_user.is_admin:
            raise PermissionError("You do not have permission to delete this repository.")

        git_path = repo.git_path
        await self._audit(
            user_id=requesting_user.id,
            event_type=AuditEventType.REPO_DELETED,
            resource_id=str(repo.id),
            metadata={"name": repo.name},
        )
        await self.db.delete(repo)
        await self.db.commit()

        # Remove from disk AFTER successful DB commit
        if os.path.exists(git_path):
            shutil.rmtree(git_path, ignore_errors=True)

    async def mark_push(self, repo: Repository) -> None:
        """Update last_push_at and mark non-empty after first push."""
        repo.last_push_at = datetime.now(timezone.utc)
        repo.is_empty = False
        await self.db.commit()

    async def _get_member(
        self, repo_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[RepositoryMember]:
        result = await self.db.execute(
            select(RepositoryMember).where(
                RepositoryMember.repository_id == repo_id,
                RepositoryMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def can_write(self, repo: Repository, user: Optional[User]) -> bool:
        """Check if user can write to the repository."""
        if not user:
            return False
        if repo.owner_id == user.id or user.is_admin:
            return True
        member = await self._get_member(repo.id, user.id)
        if member and member.role in (MemberRole.ADMIN, MemberRole.WRITE):
            return True
        return False

    async def can_read(self, repo: Repository, user: Optional[User]) -> bool:
        """Check if user can read the repository."""
        if repo.visibility == RepoVisibility.PUBLIC:
            return True
        if not user:
            return False
        if repo.owner_id == user.id or user.is_admin:
            return True
        member = await self._get_member(repo.id, user.id)
        return member is not None

    async def _audit(
        self,
        event_type: str,
        user_id: Optional[uuid.UUID] = None,
        resource_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        log = AuditLog(
            user_id=user_id,
            event_type=event_type,
            resource_type="repository",
            resource_id=resource_id,
            metadata_=metadata,
        )
        self.db.add(log)
