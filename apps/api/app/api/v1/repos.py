"""
Repository API routes — CRUD, file browser, commits, branches.
"""
import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.auth.dependencies import CurrentUser, OptionalUser, DBSession
from app.config.settings import get_settings
from app.models.repository import Repository
from app.models.user import User
from app.schemas.repository import (
    RepoCreateRequest, RepoUpdateRequest, RepoResponse, RepoListResponse,
    TreeResponse, TreeEntry, BlobResponse,
    CommitResponse, CommitDetailResponse, CommitListResponse, CommitAuthor,
    BranchResponse, BranchCreateRequest, BranchListResponse,
)
from app.services.repo_service import RepoService
from app.git.operations import GitOperations
from app.git.validator import validate_ref, validate_path

router = APIRouter(tags=["Repositories"])
settings = get_settings()


def _get_git(repo: Repository) -> GitOperations:
    return GitOperations(repo.git_path)


async def _get_accessible_repo(
    owner_username: str,
    repo_slug: str,
    current_user: Optional[User],
    db,
) -> Repository:
    svc = RepoService(db)
    repo = await svc.get_repo(owner_username, repo_slug, current_user)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")
    return repo


# ── Repository CRUD ───────────────────────────────────────────────────────────

@router.post("/repos", response_model=RepoResponse, status_code=201)
async def create_repo(
    body: RepoCreateRequest, current_user: CurrentUser, db: DBSession
):
    """Create a new repository."""
    svc = RepoService(db)
    try:
        repo = await svc.create_repo(
            owner=current_user,
            name=body.name,
            description=body.description,
            visibility=body.visibility,
            init_readme=body.init_readme,
            gitignore_template=body.gitignore_template,
            license_template=body.license_template,
            default_branch=body.default_branch,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return repo


@router.get("/repos", response_model=RepoListResponse)
async def list_my_repos(
    current_user: CurrentUser,
    db: DBSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
):
    """List the authenticated user's repositories."""
    svc = RepoService(db)
    repos, total = await svc.list_repos(
        owner=current_user,
        requesting_user=current_user,
        include_private=True,
        page=page,
        per_page=per_page,
    )
    return RepoListResponse(repos=repos, total=total)


@router.get("/users/{username}/repos", response_model=RepoListResponse)
async def list_user_repos(
    username: str,
    current_user: OptionalUser,
    db: DBSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
):
    """List a user's public repositories."""
    result = await db.execute(select(User).where(User.username == username))
    owner = result.scalar_one_or_none()
    if not owner:
        raise HTTPException(status_code=404, detail="User not found.")

    svc = RepoService(db)
    include_private = current_user is not None and (
        current_user.id == owner.id or current_user.is_admin
    )
    repos, total = await svc.list_repos(
        owner=owner,
        requesting_user=current_user,
        include_private=include_private,
        page=page,
        per_page=per_page,
    )
    return RepoListResponse(repos=repos, total=total)


@router.get("/repos/{owner}/{repo}", response_model=RepoResponse)
async def get_repo(owner: str, repo: str, current_user: OptionalUser, db: DBSession):
    """Get repository details."""
    repository = await _get_accessible_repo(owner, repo, current_user, db)
    return repository


@router.patch("/repos/{owner}/{repo}", response_model=RepoResponse)
async def update_repo(
    owner: str, repo: str, body: RepoUpdateRequest,
    current_user: CurrentUser, db: DBSession
):
    """Update repository settings."""
    repository = await _get_accessible_repo(owner, repo, current_user, db)
    svc = RepoService(db)
    if not await svc.can_write(repository, current_user):
        raise HTTPException(status_code=403, detail="Write access required.")

    if body.description is not None:
        repository.description = body.description
    if body.visibility is not None:
        repository.visibility = body.visibility
    if body.default_branch is not None:
        repository.default_branch = body.default_branch

    await db.commit()
    await db.refresh(repository, ["owner"])
    return repository


@router.delete("/repos/{owner}/{repo}", status_code=204)
async def delete_repo(
    owner: str, repo: str, current_user: CurrentUser, db: DBSession
):
    """Delete a repository (irreversible)."""
    repository = await _get_accessible_repo(owner, repo, current_user, db)
    svc = RepoService(db)
    try:
        await svc.delete_repo(repository, current_user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ── File browser ──────────────────────────────────────────────────────────────

@router.get("/repos/{owner}/{repo}/tree", response_model=TreeResponse)
async def get_tree(
    owner: str,
    repo: str,
    current_user: OptionalUser,
    db: DBSession,
    ref: str = Query("HEAD"),
    path: str = Query(""),
):
    """List files in a repository directory."""
    repository = await _get_accessible_repo(owner, repo, current_user, db)

    try:
        ref = validate_ref(ref)
        path = validate_path(path) if path else ""
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    git = _get_git(repository)
    if git.is_empty():
        return TreeResponse(tree=[], path=path, sha="", branch=ref)

    entries = git.list_tree(ref=ref, path=path)
    sha = git.get_commit_sha(ref) or ""

    tree = [
        TreeEntry(
            name=e["name"],
            path=e["path"],
            type=e["type"],
            size=e.get("size"),
            mode=e["mode"],
            sha=e["sha"],
        )
        for e in entries
    ]
    # Sort: dirs first, then files
    tree.sort(key=lambda e: (0 if e.type == "dir" else 1, e.name.lower()))

    return TreeResponse(tree=tree, path=path, sha=sha, branch=ref)


@router.get("/repos/{owner}/{repo}/blob/{path:path}", response_model=BlobResponse)
async def get_blob(
    owner: str,
    repo: str,
    path: str,
    current_user: OptionalUser,
    db: DBSession,
    ref: str = Query("HEAD"),
):
    """Get file contents."""
    repository = await _get_accessible_repo(owner, repo, current_user, db)

    try:
        ref = validate_ref(ref)
        path = validate_path(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    git = _get_git(repository)
    blob = git.get_blob(ref=ref, path=path)
    if blob is None:
        raise HTTPException(status_code=404, detail="File not found.")

    sha = git.get_commit_sha(ref) or ""
    return BlobResponse(sha=sha, **blob)


# ── Commits ───────────────────────────────────────────────────────────────────

@router.get("/repos/{owner}/{repo}/commits", response_model=CommitListResponse)
async def list_commits(
    owner: str,
    repo: str,
    current_user: OptionalUser,
    db: DBSession,
    ref: str = Query("HEAD"),
    path: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
):
    """List commits on a branch."""
    repository = await _get_accessible_repo(owner, repo, current_user, db)

    try:
        ref = validate_ref(ref)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    git = _get_git(repository)
    if git.is_empty():
        return CommitListResponse(commits=[], total=0, has_more=False)

    offset = (page - 1) * per_page
    raw_commits = git.list_commits(ref=ref, path=path, limit=per_page + 1, offset=offset)

    has_more = len(raw_commits) > per_page
    raw_commits = raw_commits[:per_page]
    total = git.count_commits(ref)

    commits = [_parse_commit(c) for c in raw_commits]
    return CommitListResponse(commits=commits, total=total, has_more=has_more)


@router.get("/repos/{owner}/{repo}/commits/{sha}", response_model=CommitDetailResponse)
async def get_commit(
    owner: str, repo: str, sha: str,
    current_user: OptionalUser, db: DBSession
):
    """Get commit details and diff."""
    repository = await _get_accessible_repo(owner, repo, current_user, db)

    try:
        sha = validate_ref(sha)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    git = _get_git(repository)
    detail = git.get_commit_detail(sha)
    if not detail:
        raise HTTPException(status_code=404, detail="Commit not found.")

    commit = _parse_commit(detail)
    return CommitDetailResponse(**commit.model_dump(), diff=detail.get("diff", ""))


# ── Branches ──────────────────────────────────────────────────────────────────

@router.get("/repos/{owner}/{repo}/branches", response_model=BranchListResponse)
async def list_branches(
    owner: str, repo: str, current_user: OptionalUser, db: DBSession
):
    """List all branches."""
    repository = await _get_accessible_repo(owner, repo, current_user, db)
    git = _get_git(repository)

    raw_branches = git.list_branches()
    default_branch = git.get_default_branch()

    branches = [
        BranchResponse(
            name=b["name"],
            sha=b["sha"],
            is_default=b["name"] == default_branch,
        )
        for b in raw_branches
    ]
    return BranchListResponse(branches=branches, default_branch=default_branch)


@router.post("/repos/{owner}/{repo}/branches", response_model=BranchResponse, status_code=201)
async def create_branch(
    owner: str, repo: str, body: BranchCreateRequest,
    current_user: CurrentUser, db: DBSession
):
    """Create a new branch."""
    repository = await _get_accessible_repo(owner, repo, current_user, db)
    svc = RepoService(db)
    if not await svc.can_write(repository, current_user):
        raise HTTPException(status_code=403, detail="Write access required.")

    git = _get_git(repository)
    success = git.create_branch(body.name, body.from_branch)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to create branch.")

    branches = {b["name"]: b["sha"] for b in git.list_branches()}
    return BranchResponse(
        name=body.name,
        sha=branches.get(body.name, ""),
        is_default=False,
    )


@router.delete("/repos/{owner}/{repo}/branches/{branch}", status_code=204)
async def delete_branch(
    owner: str, repo: str, branch: str,
    current_user: CurrentUser, db: DBSession
):
    """Delete a branch."""
    repository = await _get_accessible_repo(owner, repo, current_user, db)
    svc = RepoService(db)
    if not await svc.can_write(repository, current_user):
        raise HTTPException(status_code=403, detail="Write access required.")

    git = _get_git(repository)
    default_branch = git.get_default_branch()
    if branch == default_branch:
        raise HTTPException(status_code=400, detail="Cannot delete the default branch.")

    if not git.delete_branch(branch):
        raise HTTPException(status_code=400, detail="Failed to delete branch.")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_commit(c: dict) -> CommitResponse:
    from datetime import datetime
    def parse_author(d: dict) -> CommitAuthor:
        try:
            dt = datetime.fromisoformat(d["date"])
        except Exception:
            from datetime import timezone
            dt = datetime.now(timezone.utc)
        return CommitAuthor(name=d["name"], email=d["email"], date=dt)

    return CommitResponse(
        sha=c["sha"],
        short_sha=c["short_sha"],
        message=c["message"],
        author=parse_author(c["author"]),
        committer=parse_author(c["committer"]),
        parent_shas=c.get("parent_shas", []),
    )
