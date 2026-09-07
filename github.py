from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import httpx

from documents import Document

USER_AGENT = "SearchengineBot/0.1 (+local)"
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
MAX_FILE_BYTES = 200_000

SKIP_DIR_PARTS = {
    ".git",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    "venv",
}

SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".zip", ".gz", ".tar", ".woff", ".woff2", ".ttf",
    ".mp4", ".mp3", ".exe", ".dll", ".so", ".dylib", ".class",
    ".lock", ".min.js", ".min.css",
}

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".md": "markdown",
    ".txt": "text",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".html": "html",
    ".css": "css",
    ".sh": "shell",
    ".sql": "sql",
}


def parse_repo(spec: str) -> tuple[str, str]:
    """Accept 'owner/repo' or a github.com URL. Returns (owner, repo)."""
    spec = (spec or "").strip().rstrip("/")
    if not spec:
        raise ValueError("Need a GitHub repo like owner/repo")

    if spec.startswith("http://") or spec.startswith("https://"):
        parsed = urlparse(spec)
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            raise ValueError("Only github.com URLs are supported")
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            raise ValueError("GitHub URL must include owner and repo")
        return parts[0], parts[1].removesuffix(".git")

    parts = spec.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("Need a GitHub repo like owner/repo")
    return parts[0], parts[1].removesuffix(".git")


def language_for(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return LANGUAGE_BY_SUFFIX.get(suffix, suffix.lstrip(".") if suffix else "")


def should_index_path(path: str) -> bool:
    parts = Path(path).parts
    if any(part in SKIP_DIR_PARTS for part in parts):
        return False
    lower = path.lower()
    if any(lower.endswith(suffix) for suffix in SKIP_SUFFIXES):
        return False
    return True


def _headers() -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_repo_files(
    spec: str,
    max_files: int = 50,
    client: httpx.Client | None = None,
) -> list[Document]:
    """Download text files from a public GitHub repo and turn them into Documents."""
    owner, repo = parse_repo(spec)
    repo_name = f"{owner}/{repo}"
    owned = client is None
    if owned:
        client = httpx.Client(follow_redirects=True, timeout=20.0, headers=_headers())
    assert client is not None
    try:
        meta = client.get(f"{API}/repos/{owner}/{repo}")
        if meta.status_code == 404:
            raise ValueError(f"GitHub repo not found: {repo_name}")
        meta.raise_for_status()
        default_branch = meta.json().get("default_branch") or "main"

        tree = client.get(
            f"{API}/repos/{owner}/{repo}/git/trees/{default_branch}",
            params={"recursive": "1"},
        )
        tree.raise_for_status()
        entries = tree.json().get("tree") or []

        docs: list[Document] = []
        for entry in entries:
            if len(docs) >= max_files:
                break
            if entry.get("type") != "blob":
                continue
            path = entry.get("path") or ""
            if not should_index_path(path):
                continue
            size = int(entry.get("size") or 0)
            if size > MAX_FILE_BYTES:
                continue
            text = _download_file(client, owner, repo, default_branch, path)
            if text is None:
                continue
            docs.append(
                Document(
                    url=f"https://github.com/{owner}/{repo}/blob/{default_branch}/{path}",
                    title=path,
                    text=text,
                    repo_name=repo_name,
                    file_path=path,
                    language=language_for(path),
                    status=200,
                )
            )
        return docs
    finally:
        if owned:
            client.close()


def _download_file(
    client: httpx.Client,
    owner: str,
    repo: str,
    branch: str,
    path: str,
) -> str | None:
    url = f"{RAW}/{owner}/{repo}/{branch}/{path}"
    try:
        response = client.get(url)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    content_type = response.headers.get("content-type", "")
    if "octet-stream" in content_type.lower():
        return None
    try:
        return response.text
    except UnicodeDecodeError:
        return None
