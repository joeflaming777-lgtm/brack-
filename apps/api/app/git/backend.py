"""
Git Smart HTTP backend — proxies git push/pull/clone to git http-backend CGI.
This is the real Git protocol implementation.
"""
import os
import asyncio
import subprocess
from typing import AsyncGenerator, Optional

from fastapi import Request, Response
from fastapi.responses import StreamingResponse

from app.config.settings import get_settings


async def handle_git_http(
    request: Request,
    repo_path: str,
    service: Optional[str] = None,
) -> Response:
    """
    Handle Git Smart HTTP protocol by delegating to git http-backend.
    
    Supports:
    - GET /info/refs?service=git-upload-pack   (clone/fetch)
    - GET /info/refs?service=git-receive-pack  (push)
    - POST /git-upload-pack                    (clone/fetch data)
    - POST /git-receive-pack                   (push data)
    - GET /info/refs                           (dumb transport)
    - GET /objects/...                         (dumb transport)
    """
    settings = get_settings()

    if not os.path.isdir(repo_path):
        return Response(status_code=404, content=b"Repository not found.")

    # Build environment for git http-backend
    path_info = request.url.path
    query_string = str(request.url.query)
    content_type = request.headers.get("content-type", "")
    content_length = request.headers.get("content-length", "")

    env = {
        **os.environ,
        "GIT_PROJECT_ROOT": settings.BRACK_STORAGE_PATH,
        "GIT_HTTP_EXPORT_ALL": "1",
        "PATH_INFO": _extract_git_path(path_info),
        "QUERY_STRING": query_string,
        "REQUEST_METHOD": request.method,
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": content_length,
        "SERVER_PROTOCOL": "HTTP/1.1",
        "SERVER_SOFTWARE": "brack/1.0",
        "HTTP_HOST": request.headers.get("host", "localhost"),
        "REMOTE_ADDR": request.client.host if request.client else "127.0.0.1",
    }

    # Read request body for POST requests
    body = b""
    if request.method == "POST":
        body = await request.body()

    # Spawn git http-backend
    try:
        process = await asyncio.create_subprocess_exec(
            "git", "http-backend",
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=body),
            timeout=300,  # 5 min for large pushes
        )
    except FileNotFoundError:
        return Response(
            status_code=500,
            content=b"git is not installed on the server.",
        )
    except asyncio.TimeoutError:
        return Response(status_code=504, content=b"Git operation timed out.")

    if process.returncode != 0:
        return Response(
            status_code=500,
            content=stderr or b"Git operation failed.",
        )

    # Parse CGI response headers
    headers, body_start = _parse_cgi_headers(stdout)
    status_code = 200

    if "Status" in headers:
        try:
            status_code = int(headers.pop("Status").split(" ")[0])
        except (ValueError, IndexError):
            pass

    response_body = stdout[body_start:]

    return Response(
        content=response_body,
        status_code=status_code,
        headers=headers,
    )


def _extract_git_path(url_path: str) -> str:
    """
    Extract the git path from the URL.
    Example: /joe/my-project.git/info/refs -> /joe/my-project.git/info/refs
    """
    # The PATH_INFO for git http-backend should be relative to GIT_PROJECT_ROOT
    # We strip the /<owner>/<repo>.git prefix and keep the rest
    parts = url_path.lstrip("/").split("/", 2)
    if len(parts) >= 3:
        return "/" + "/".join(parts[1:])  # /<repo>.git/<path>
    elif len(parts) == 2:
        return "/" + parts[1]
    return url_path


def _parse_cgi_headers(output: bytes) -> tuple[dict, int]:
    """
    Parse CGI output headers from git http-backend response.
    Returns (headers_dict, body_start_index).
    """
    headers = {}
    # Find the blank line separating headers from body
    separator = b"\r\n\r\n"
    sep_idx = output.find(separator)
    if sep_idx == -1:
        separator = b"\n\n"
        sep_idx = output.find(separator)

    if sep_idx == -1:
        return {}, 0

    header_section = output[:sep_idx].decode("utf-8", errors="replace")
    body_start = sep_idx + len(separator)

    for line in header_section.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip()] = value.strip()

    return headers, body_start
