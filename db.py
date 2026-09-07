from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "index.db"

_PAGE_COLUMNS = {
    "repo_name": "TEXT NOT NULL DEFAULT ''",
    "file_path": "TEXT NOT NULL DEFAULT ''",
    "language": "TEXT NOT NULL DEFAULT ''",
}


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path is not None else DB_PATH
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
    else:
        conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY,
            url TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '',
            status INTEGER,
            crawled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            repo_name TEXT NOT NULL DEFAULT '',
            file_path TEXT NOT NULL DEFAULT '',
            language TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS postings (
            term TEXT NOT NULL,
            page_id INTEGER NOT NULL,
            tf INTEGER NOT NULL,
            PRIMARY KEY (term, page_id),
            FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_postings_term ON postings(term);
        """
    )
    existing = {
        row["name"] for row in conn.execute("PRAGMA table_info(pages)")
    }
    for name, spec in _PAGE_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE pages ADD COLUMN {name} {spec}")
    conn.commit()
