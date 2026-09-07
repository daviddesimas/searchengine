# Searchengine

A small local search engine. You can crawl HTML pages and/or pull files from a GitHub repo, store them as documents, build a term postings list, and query it from the CLI or a web UI.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional: set `GITHUB_TOKEN` (or `GH_TOKEN`) to raise GitHub API rate limits.

## Run

Index a website (same host, follows `robots.txt` disallows):

```bash
python main.py crawl https://example.com --max-pages 20
```

Index files from a public GitHub repo:

```bash
python main.py github owner/repo --max-files 50
```

Start the UI at http://127.0.0.1:8000

```bash
python main.py serve
```

JSON search: `GET /api/search?q=hello`

Tests:

```bash
python -m unittest test_core.py
```

## Layout

| File | Role |
| --- | --- |
| `github.py` | Fetch repo files from GitHub and turn them into documents |
| `crawler.py` | Fetch HTML pages, extract text/links, respect robots |
| `documents.py` | `Document` model (id, repo, path, url, language, text) |
| `tokens.py` | Lowercase tokenization and stopword removal |
| `indexer.py` | Store documents + term postings in SQLite |
| `db.py` | SQLite connection and schema |
| `search.py` | Query tokens → postings lookup → BM25 rank (existing) |
| `app.py` | FastAPI UI and `/api/search` |
| `main.py` | CLI: `crawl`, `github`, `serve`, `stats` |
