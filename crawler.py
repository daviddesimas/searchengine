from __future__ import annotations

from collections import deque
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from documents import Document
from indexer import index_document

USER_AGENT = "SearchengineBot/0.1 (+local)"
SKIP_SCHEMES = {"mailto", "javascript", "tel", "data"}
SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".zip", ".css", ".js", ".mp4", ".mp3", ".woff", ".woff2",
}


def crawl(seed: str, max_pages: int = 30, same_host: bool = True) -> dict:
    seed = _normalize(seed)
    if not seed:
        raise ValueError("Need a valid http(s) seed URL")

    host = urlparse(seed).netloc
    robots = _load_robots(seed)
    seen: set[str] = set()
    queue: deque[str] = deque([seed])
    crawled: list[str] = []
    skipped = 0
    last_error = ""

    with httpx.Client(follow_redirects=True, timeout=12.0, headers={"User-Agent": USER_AGENT}) as client:
        while queue and len(crawled) < max_pages:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)

            if same_host and urlparse(url).netloc != host:
                skipped += 1
                last_error = f"skipped off-host URL: {url}"
                continue
            if _blocked(url, robots):
                skipped += 1
                last_error = f"blocked by robots.txt: {url}"
                continue

            try:
                response = client.get(url)
            except httpx.HTTPError as exc:
                skipped += 1
                last_error = f"could not fetch {url} ({exc})"
                continue

            if response.status_code >= 400:
                skipped += 1
                last_error = f"HTTP {response.status_code} for {url}"
                continue

            content_type = response.headers.get("content-type", "")
            if "html" not in content_type.lower() and not url.rstrip("/").endswith((".html", ".htm")):
                skipped += 1
                last_error = f"not HTML: {url}"
                continue

            title, text, links = _extract(url, response.text)
            page_url = str(response.url)
            index_document(
                Document(
                    url=page_url,
                    title=title,
                    text=text,
                    status=response.status_code,
                    language="html",
                )
            )
            crawled.append(page_url)

            for link in links:
                if link not in seen:
                    queue.append(link)

    return {
        "crawled": crawled,
        "count": len(crawled),
        "skipped": skipped,
        "queued": len(queue),
        "error": last_error,
    }


def _normalize(url: str) -> str:
    url = (url or "").strip()
    if url and not urlparse(url).scheme:
        url = "https://" + url
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def _extract(base_url: str, html: str) -> tuple[str, str, list[str]]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "footer"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        heading = soup.find(["h1", "h2"])
        title = heading.get_text(" ", strip=True) if heading else base_url

    text = soup.get_text(" ", strip=True)
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = _normalize(urljoin(base_url, anchor["href"]))
        if not href:
            continue
        parsed = urlparse(href)
        if parsed.scheme in SKIP_SCHEMES:
            continue
        path = parsed.path.lower()
        if any(path.endswith(suffix) for suffix in SKIP_SUFFIXES):
            continue
        links.append(href)
    return title, text, links


def _load_robots(seed: str) -> list[str]:
    parsed = urlparse(seed)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    disallows: list[str] = []
    try:
        with httpx.Client(timeout=6.0, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(robots_url)
            if response.status_code != 200:
                return []
            applicable = False
            for line in response.text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip().lower()
                value = value.strip()
                if key == "user-agent":
                    applicable = value == "*" or "searchengine" in value.lower()
                elif key == "disallow" and applicable and value:
                    disallows.append(value)
    except httpx.HTTPError:
        return []
    return disallows


def _blocked(url: str, disallows: list[str]) -> bool:
    path = urlparse(url).path or "/"
    for rule in disallows:
        if path.startswith(rule):
            return True
    return False
