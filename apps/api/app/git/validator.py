"""
Path traversal protection for Git operations.
"""
import os
import re


def validate_ref(ref: str) -> str:
    """Validate a git ref (branch name, commit SHA, tag)."""
    # Allow: alphanumeric, hyphens, slashes, dots, underscores, @
    if not re.match(r"^[a-zA-Z0-9._\-/@^~:]+$", ref):
        raise ValueError(f"Invalid git ref: {ref!r}")
    # Disallow path traversal
    if ".." in ref:
        raise ValueError(f"Invalid git ref (path traversal): {ref!r}")
    return ref


def validate_path(path: str) -> str:
    """Validate a file path within a repository."""
    if not path:
        return ""
    # Normalize
    normalized = os.path.normpath(path).replace("\\", "/")
    # Must not start with /
    if normalized.startswith("/"):
        raise ValueError(f"Absolute paths not allowed: {path!r}")
    # Must not contain ..
    if ".." in normalized.split("/"):
        raise ValueError(f"Path traversal not allowed: {path!r}")
    return normalized


def validate_repo_path(storage_root: str, repo_path: str) -> str:
    """
    Ensure repo_path is within storage_root.
    Raises ValueError on path traversal attempt.
    """
    storage_root = os.path.abspath(storage_root)
    repo_path = os.path.abspath(repo_path)
    if not repo_path.startswith(storage_root + os.sep) and repo_path != storage_root:
        raise ValueError(f"Path traversal detected: {repo_path!r}")
    return repo_path
