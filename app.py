from __future__ import annotations

from pathlib import Path

from urllib.parse import quote

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from crawler import crawl
from github import fetch_repo_files
from indexer import index_documents, page_count
from search import search

app = FastAPI(title="Searchengine")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = Query(""), error: str = Query("")):
    hits = search(q) if q.strip() else []
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "q": q,
            "hits": hits,
            "indexed": page_count(),
            "error": error,
        },
    )


def _error_redirect(message: str) -> RedirectResponse:
    return RedirectResponse(f"/?error={quote(message)}", status_code=303)


@app.post("/crawl")
def start_crawl(url: str = Form(...), max_pages: int = Form(20)):
    max_pages = max(1, min(int(max_pages), 80))
    try:
        result = crawl(url, max_pages=max_pages)
    except Exception as exc:
        return _error_redirect(f"Crawl failed: {exc}")
    if result["count"] == 0:
        detail = result.get("error") or f"{result['skipped']} URL(s) skipped"
        return _error_redirect(f"Crawl failed: no pages indexed. {detail}")
    return RedirectResponse("/", status_code=303)


@app.post("/github")
def start_github(repo: str = Form(...), max_files: int = Form(50)):
    max_files = max(1, min(int(max_files), 80))
    try:
        docs = fetch_repo_files(repo, max_files=max_files)
        index_documents(docs)
    except Exception as exc:
        return _error_redirect(f"GitHub fetch failed: {exc}")
    return RedirectResponse("/", status_code=303)


@app.get("/api/search")
def api_search(q: str = Query("")):
    hits = search(q)
    return {"query": q, "count": len(hits), "results": [hit.__dict__ for hit in hits]}
