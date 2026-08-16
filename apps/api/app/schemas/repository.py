"""
Pydantic schemas for repository endpoints.
"""
import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, field_validator
import re

from app.models.repository import RepoVisibility

REPO_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]{1,100}$")


class RepoCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    visibility: RepoVisibility = RepoVisibility.PRIVATE
    init_readme: bool = False
    gitignore_template: Optional[str] = None
    license_template: Optional[str] = None
    default_branch: str = "main"

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not REPO_NAME_PATTERN.match(v):
            raise ValueError(
                "Repository name must be 1-100 characters, using letters, numbers, "
                "hyphens, underscores, and dots only."
            )
        return v


class RepoUpdateRequest(BaseModel):
    description: Optional[str] = None
    visibility: Optional[RepoVisibility] = None
    default_branch: Optional[str] = None


class OwnerResponse(BaseModel):
    id: uuid.UUID
    username: str
    display_name: Optional[str]
    avatar_url: Optional[str]

    model_config = {"from_attributes": True}


class RepoResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: Optional[str]
    visibility: RepoVisibility
    default_branch: str
    is_empty: bool
    is_archived: bool
    stars_count: int
    forks_count: int
    open_issues_count: int
    created_at: datetime
    updated_at: datetime
    last_push_at: Optional[datetime]
    owner: OwnerResponse

    model_config = {"from_attributes": True}


class RepoListResponse(BaseModel):
    repos: List[RepoResponse]
    total: int


# ── Git tree / blob ──────────────────────────────────────────────────────────

class TreeEntry(BaseModel):
    name: str
    path: str
    type: str  # "blob" | "tree"
    size: Optional[int]
    mode: str
    sha: str


class TreeResponse(BaseModel):
    tree: List[TreeEntry]
    path: str
    sha: str  # commit sha
    branch: str


class BlobResponse(BaseModel):
    path: str
    content: str
    encoding: str = "utf-8"
    size: int
    sha: str
    language: Optional[str]
    is_binary: bool = False


# ── Commits ──────────────────────────────────────────────────────────────────

class CommitAuthor(BaseModel):
    name: str
    email: str
    date: datetime


class CommitResponse(BaseModel):
    sha: str
    short_sha: str
    message: str
    author: CommitAuthor
    committer: CommitAuthor
    parent_shas: List[str]
    files_changed: Optional[int] = None


class CommitDetailResponse(CommitResponse):
    diff: str  # unified diff


class CommitListResponse(BaseModel):
    commits: List[CommitResponse]
    total: int
    has_more: bool


# ── Branches ─────────────────────────────────────────────────────────────────

class BranchResponse(BaseModel):
    name: str
    sha: str
    is_default: bool
    is_protected: bool = False
    ahead_count: Optional[int] = None
    behind_count: Optional[int] = None


class BranchCreateRequest(BaseModel):
    name: str
    from_branch: str = "main"

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or "/" in v.strip("/") or v.startswith("-"):
            raise ValueError("Invalid branch name.")
        return v


class BranchListResponse(BaseModel):
    branches: List[BranchResponse]
    default_branch: str


# ── Personal Access Tokens ────────────────────────────────────────────────────

class TokenCreateRequest(BaseModel):
    name: str
    scopes: List[str] = ["repo:read", "repo:write"]
    expires_days: Optional[int] = None  # None = never


class TokenCreateResponse(BaseModel):
    id: uuid.UUID
    name: str
    token: str  # shown ONCE
    prefix: str
    scopes: List[str]
    created_at: datetime
    expires_at: Optional[datetime]


class TokenListItem(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: List[str]
    last_used_at: Optional[datetime]
    created_at: datetime
    expires_at: Optional[datetime]

    model_config = {"from_attributes": True}
