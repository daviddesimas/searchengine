from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Document:
    """One searchable item: a crawled HTML page or a GitHub file."""

    url: str
    title: str = ""
    text: str = ""
    repo_name: str = ""
    file_path: str = ""
    language: str = ""
    status: int | None = 200
    id: int | None = None

    @property
    def github_url(self) -> str:
        return self.url
