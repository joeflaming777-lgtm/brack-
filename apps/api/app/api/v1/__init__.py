"""
API v1 router — registers all sub-routers.
"""
from fastapi import APIRouter

from app.api.v1 import auth, repos, git

router = APIRouter()

router.include_router(auth.router)
router.include_router(repos.router)

# Git HTTP transport — must be last (catch-all patterns)
# These routes handle /{owner}/{repo}.git/... URLs
router.include_router(git.router)
