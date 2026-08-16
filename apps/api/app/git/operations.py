"""
Git operations — wraps git CLI for repository inspection.
All operations are read-only for the API layer.
Write operations happen via git http-backend.
"""
import os
import re
import subprocess
import base64
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any


BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".svg",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".whl",
    ".mp4", ".mp3", ".wav", ".ogg", ".flac",
    ".ttf", ".otf", ".woff", ".woff2",
    ".pyc", ".pyo", ".pyd",
}

LANGUAGE_MAP = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "jsx", ".tsx": "tsx", ".html": "html", ".css": "css",
    ".scss": "scss", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".md": "markdown", ".mdx": "mdx", ".sh": "shell", ".bash": "shell",
    ".zsh": "shell", ".fish": "shell", ".rs": "rust", ".go": "go",
    ".java": "java", ".kt": "kotlin", ".swift": "swift", ".c": "c",
    ".cpp": "cpp", ".h": "c", ".hpp": "cpp", ".cs": "csharp",
    ".rb": "ruby", ".php": "php", ".sql": "sql", ".graphql": "graphql",
    ".toml": "toml", ".ini": "ini", ".env": "shell", ".dockerfile": "dockerfile",
    ".xml": "xml", ".tf": "hcl", ".hcl": "hcl", ".lua": "lua",
    ".r": "r", ".dart": "dart", ".vue": "vue", ".svelte": "svelte",
}


def _run_git(args: list[str], cwd: str, input_data: bytes = None) -> subprocess.CompletedProcess:
    """Run a git command, raising on error."""
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        input=input_data,
        timeout=30,
    )


class GitOperations:
    """
    High-level Git operations for a single bare repository.
    """

    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def init_bare(
        self,
        default_branch: str = "main",
        init_readme: bool = False,
        repo_name: str = "",
        description: Optional[str] = None,
    ) -> None:
        """Initialize a bare git repository."""
        os.makedirs(self.repo_path, exist_ok=True)

        result = _run_git(
            ["init", "--bare", f"--initial-branch={default_branch}", self.repo_path],
            cwd=os.path.dirname(self.repo_path),
        )
        if result.returncode != 0:
            # Fallback for older git versions that don't support --initial-branch
            _run_git(["init", "--bare", self.repo_path], cwd=os.path.dirname(self.repo_path))

        # Write description
        desc_path = os.path.join(self.repo_path, "description")
        with open(desc_path, "w") as f:
            f.write(description or f"{repo_name} repository" or "")

        # Enable http-backend
        config_path = os.path.join(self.repo_path, "config")
        with open(config_path, "a") as f:
            f.write("\n[http]\n\treceivepack = true\n")

        if init_readme:
            self._create_initial_commit(repo_name, description, default_branch)

    def _create_initial_commit(
        self, repo_name: str, description: Optional[str], default_branch: str
    ) -> None:
        """Create an initial commit with README.md using git fast-import."""
        import tempfile, time

        readme_content = f"# {repo_name}\n\n{description or ''}\n"
        readme_bytes = readme_content.encode("utf-8")
        ts = int(time.time())

        fast_import_data = (
            f"blob\nmark :1\ndata {len(readme_bytes)}\n".encode()
            + readme_bytes
            + f"\ncommit refs/heads/{default_branch}\n"
            f"mark :2\n"
            f"author Brack <brack@localhost> {ts} +0000\n"
            f"committer Brack <brack@localhost> {ts} +0000\n"
            f"data 16\n"
            f"Initial commit\n"
            f"M 100644 :1 README.md\n"
            f"\n"
        ).encode()

        _run_git(["fast-import", "--quiet"], cwd=self.repo_path, input_data=fast_import_data)
        _run_git(["update-server-info"], cwd=self.repo_path)

    def exists(self) -> bool:
        return os.path.isdir(self.repo_path) and os.path.exists(
            os.path.join(self.repo_path, "HEAD")
        )

    def is_empty(self) -> bool:
        result = _run_git(["rev-list", "--count", "HEAD"], cwd=self.repo_path)
        if result.returncode != 0:
            return True
        return result.stdout.strip() == b"0"

    def list_branches(self) -> List[Dict[str, Any]]:
        result = _run_git(
            ["branch", "--format=%(refname:short) %(objectname)"], cwd=self.repo_path
        )
        branches = []
        for line in result.stdout.decode().strip().splitlines():
            parts = line.strip().split(" ", 1)
            if len(parts) == 2:
                branches.append({"name": parts[0], "sha": parts[1]})
        return branches

    def get_default_branch(self) -> str:
        result = _run_git(["symbolic-ref", "--short", "HEAD"], cwd=self.repo_path)
        if result.returncode == 0:
            return result.stdout.decode().strip()
        return "main"

    def list_tree(self, ref: str = "HEAD", path: str = "") -> List[Dict[str, Any]]:
        """List directory contents at a given path."""
        tree_ref = f"{ref}:{path}" if path else ref
        result = _run_git(
            ["ls-tree", "--long", tree_ref], cwd=self.repo_path
        )
        if result.returncode != 0:
            return []

        entries = []
        for line in result.stdout.decode().strip().splitlines():
            # Format: <mode> <type> <sha>\t<size>\t<name>
            # or: <mode> SP <type> SP <sha> SP <size> TAB <name>
            match = re.match(
                r"^(\d+)\s+(blob|tree)\s+([0-9a-f]+)\s+(-|\d+)\s+(.+)$", line
            )
            if match:
                mode, obj_type, sha, size_str, name = match.groups()
                entry_path = f"{path}/{name}".lstrip("/") if path else name
                entries.append({
                    "name": name,
                    "path": entry_path,
                    "type": "file" if obj_type == "blob" else "dir",
                    "size": int(size_str) if size_str != "-" else None,
                    "mode": mode,
                    "sha": sha,
                })
        return entries

    def get_blob(self, ref: str, path: str) -> Optional[Dict[str, Any]]:
        """Get file contents at a given ref."""
        result = _run_git(["show", f"{ref}:{path}"], cwd=self.repo_path)
        if result.returncode != 0:
            return None

        ext = Path(path).suffix.lower()
        is_binary = ext in BINARY_EXTENSIONS

        if is_binary:
            content = base64.b64encode(result.stdout).decode()
            encoding = "base64"
        else:
            try:
                content = result.stdout.decode("utf-8")
                encoding = "utf-8"
            except UnicodeDecodeError:
                content = base64.b64encode(result.stdout).decode()
                encoding = "base64"
                is_binary = True

        return {
            "path": path,
            "content": content,
            "encoding": encoding,
            "size": len(result.stdout),
            "language": LANGUAGE_MAP.get(ext),
            "is_binary": is_binary,
        }

    def get_commit_sha(self, ref: str = "HEAD") -> Optional[str]:
        result = _run_git(["rev-parse", ref], cwd=self.repo_path)
        if result.returncode != 0:
            return None
        return result.stdout.decode().strip()

    def list_commits(
        self,
        ref: str = "HEAD",
        path: Optional[str] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List commits on a branch."""
        fmt = "%H%x00%h%x00%s%x00%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI%x00%P"
        args = ["log", f"--format={fmt}", f"--skip={offset}", f"--max-count={limit}", ref]
        if path:
            args += ["--", path]

        result = _run_git(args, cwd=self.repo_path)
        if result.returncode != 0:
            return []

        commits = []
        for line in result.stdout.decode().strip().splitlines():
            parts = line.split("\x00")
            if len(parts) < 10:
                continue
            sha, short_sha, msg, an, ae, ai, cn, ce, ci, parents = parts[:10]
            commits.append({
                "sha": sha,
                "short_sha": short_sha,
                "message": msg,
                "author": {"name": an, "email": ae, "date": ai},
                "committer": {"name": cn, "email": ce, "date": ci},
                "parent_shas": [p for p in parents.split(" ") if p],
            })
        return commits

    def count_commits(self, ref: str = "HEAD") -> int:
        result = _run_git(["rev-list", "--count", ref], cwd=self.repo_path)
        if result.returncode != 0:
            return 0
        try:
            return int(result.stdout.decode().strip())
        except ValueError:
            return 0

    def get_commit_detail(self, sha: str) -> Optional[Dict[str, Any]]:
        """Get commit info + unified diff."""
        fmt = "%H%x00%h%x00%s%x00%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI%x00%P"
        result = _run_git(["show", f"--format={fmt}", "--stat", sha], cwd=self.repo_path)
        if result.returncode != 0:
            return None

        lines = result.stdout.decode(errors="replace").split("\n")
        header = lines[0].split("\x00")
        if len(header) < 10:
            return None

        sha, short_sha, msg, an, ae, ai, cn, ce, ci, parents = header[:10]

        # Get the diff separately
        diff_result = _run_git(
            ["diff", f"{sha}^", sha, "--unified=3"], cwd=self.repo_path
        )
        diff = diff_result.stdout.decode(errors="replace") if diff_result.returncode == 0 else ""

        return {
            "sha": sha,
            "short_sha": short_sha,
            "message": msg,
            "author": {"name": an, "email": ae, "date": ai},
            "committer": {"name": cn, "email": ce, "date": ci},
            "parent_shas": [p for p in parents.split(" ") if p],
            "diff": diff,
        }

    def create_branch(self, name: str, from_ref: str = "HEAD") -> bool:
        """Create a new branch."""
        result = _run_git(
            ["branch", name, from_ref], cwd=self.repo_path
        )
        return result.returncode == 0

    def delete_branch(self, name: str) -> bool:
        """Delete a branch."""
        result = _run_git(
            ["branch", "-D", name], cwd=self.repo_path
        )
        return result.returncode == 0

    def update_server_info(self) -> None:
        """Update auxiliary info files for dumb HTTP transport."""
        _run_git(["update-server-info"], cwd=self.repo_path)
