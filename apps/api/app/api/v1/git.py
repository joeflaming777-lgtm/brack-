"""
Git Smart HTTP transport routes.
Handles: git clone, git push, git pull, git fetch.

URL patterns:
  GET  /{owner}/{repo}.git/info/refs?service=git-upload-pack
  GET  /{owner}/{repo}.git/info/refs?service=git-receive-pack
  POST /{owner}/{repo}.git/git-upload-pack
  POST /{owner}/{repo}.git/git-receive-pack
  GET  /{owner}/{repo}.git/HEAD
  GET  /{owner}/{repo}.git/objects/...
"""
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.auth.dependencies import get_current_user_optional, DBSession
from app.config.settings import get_settings
from app.database import get_db
from app.git.backend import handle_git_http
from app.git.validator import validate_repo_path
from app.models.repository import Repository, RepoVisibility
from app.models.user import User
from app.models.audit import AuditLog, AuditEventType
from app.services.repo_service import RepoService


router = APIRouter(tags=["Git HTTP"])
settings = get_settings()


async def _resolve_repo(
    owner: str,
    repo_slug: str,
    db: AsyncSession,
    current_user: Optional[User],
    require_write: bool = False,
) -> Repository:
    """Resolve a repository and check access."""
    svc = RepoService(db)
    # Remove .git suffix if present
    if repo_slug.endswith(".git"):
        repo_slug = repo_slug[:-4]

    repo = await svc.get_repo(owner, repo_slug, current_user)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")

    if require_write:
        if not await svc.can_write(repo, current_user):
            raise HTTPException(
                status_code=401,
                detail="Authentication required.",
                headers={"WWW-Authenticate": 'Basic realm="Brack"'},
            )

    return repo


@router.api_route(
    "/{owner}/{repo_name:path}/info/refs",
    methods=["GET"],
)
async def git_info_refs(
    owner: str,
    repo_name: str,
    request: Request,
    db: DBSession,
    service: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Git Smart HTTP — info/refs endpoint."""
    # Strip .git suffix from repo_name (may include subpath)
    slug = repo_name.split("/")[0]
    if slug.endswith(".git"):
        slug = slug[:-4]

    require_write = service == "git-receive-pack"
    repo = await _resolve_repo(owner, slug, db, current_user, require_write)

    # Audit git clone/pull
    if service == "git-upload-pack":
        db.add(AuditLog(
            user_id=current_user.id if current_user else None,
            event_type=AuditEventType.GIT_CLONE,
            resource_type="repository",
            resource_id=str(repo.id),
            ip_address=request.client.host if request.client else None,
        ))
        await db.commit()

    try:
        validate_repo_path(settings.BRACK_STORAGE_PATH, repo.git_path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid repository path.")

    return await handle_git_http(request, repo.git_path, service=service)


@router.api_route(
    "/{owner}/{repo_name:path}/git-upload-pack",
    methods=["POST"],
)
async def git_upload_pack(
    owner: str,
    repo_name: str,
    request: Request,
    db: DBSession,
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Git Smart HTTP — upload-pack (clone/fetch data)."""
    slug = repo_name.split("/")[0]
    if slug.endswith(".git"):
        slug = slug[:-4]

    repo = await _resolve_repo(owner, slug, db, current_user, require_write=False)
    return await handle_git_http(request, repo.git_path)


@router.api_route(
    "/{owner}/{repo_name:path}/git-receive-pack",
    methods=["POST"],
)
async def git_receive_pack(
    owner: str,
    repo_name: str,
    request: Request,
    db: DBSession,
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Git Smart HTTP — receive-pack (push data)."""
    slug = repo_name.split("/")[0]
    if slug.endswith(".git"):
        slug = slug[:-4]

    repo = await _resolve_repo(owner, slug, db, current_user, require_write=True)

    # Process the git operation
    response = await handle_git_http(request, repo.git_path)

    # If push succeeded, mark the repo as non-empty and update push timestamp
    if response.status_code == 200:
        svc = RepoService(db)
        await svc.mark_push(repo)
        db.add(AuditLog(
            user_id=current_user.id if current_user else None,
            event_type=AuditEventType.GIT_PUSH,
            resource_type="repository",
            resource_id=str(repo.id),
            ip_address=request.client.host if request.client else None,
        ))
        await db.commit()

    return response


@router.api_route(
    "/{owner}/{repo_name:path}/HEAD",
    methods=["GET"],
)
async def git_head(
    owner: str,
    repo_name: str,
    request: Request,
    db: DBSession,
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Git HEAD file (dumb transport)."""
    slug = repo_name.split("/")[0]
    if slug.endswith(".git"):
        slug = slug[:-4]

    repo = await _resolve_repo(owner, slug, db, current_user)
    return await handle_git_http(request, repo.git_path)


@router.api_route(
    "/{owner}/{repo_name:path}/objects/{object_path:path}",
    methods=["GET"],
)
async def git_objects(
    owner: str,
    repo_name: str,
    object_path: str,
    request: Request,
    db: DBSession,
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Git objects (dumb transport)."""
    slug = repo_name.split("/")[0]
    if slug.endswith(".git"):
        slug = slug[:-4]

    repo = await _resolve_repo(owner, slug, db, current_user)
    return await handle_git_http(request, repo.git_path)
