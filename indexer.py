from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Iterable

from db import connect, init_db
from documents import Document
from tokens import tokenize


def _open(conn: sqlite3.Connection | None) -> tuple[sqlite3.Connection, bool]:
    if conn is not None:
        return conn, False
    opened = connect()
    init_db(opened)
    return opened, True


def index_document(doc: Document, conn: sqlite3.Connection | None = None) -> int:
    """Store a document and rebuild its inverted-index postings (term -> tf)."""
    tokens = tokenize(f"{doc.title} {doc.text}")
    counts = Counter(tokens)
    db, owned = _open(conn)
    try:
        existing = db.execute("SELECT id FROM pages WHERE url = ?", (doc.url,)).fetchone()
        if existing:
            page_id = int(existing["id"])
            db.execute(
                """
                UPDATE pages
                SET title = ?, text = ?, status = ?, crawled_at = CURRENT_TIMESTAMP,
                    repo_name = ?, file_path = ?, language = ?
                WHERE id = ?
                """,
                (
                    doc.title,
                    doc.text,
                    doc.status,
                    doc.repo_name,
                    doc.file_path,
                    doc.language,
                    page_id,
                ),
            )
            db.execute("DELETE FROM postings WHERE page_id = ?", (page_id,))
        else:
            cur = db.execute(
                """
                INSERT INTO pages (url, title, text, status, repo_name, file_path, language)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc.url,
                    doc.title,
                    doc.text,
                    doc.status,
                    doc.repo_name,
                    doc.file_path,
                    doc.language,
                ),
            )
            page_id = int(cur.lastrowid)

        db.executemany(
            "INSERT INTO postings (term, page_id, tf) VALUES (?, ?, ?)",
            [(term, page_id, tf) for term, tf in counts.items()],
        )
        if owned:
            db.commit()
        doc.id = page_id
        return page_id
    finally:
        if owned:
            db.close()


def index_page(
    url: str,
    title: str,
    text: str,
    status: int | None = 200,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Backward-compatible helper used by the HTML crawler."""
    return index_document(
        Document(url=url, title=title, text=text, status=status, language="html"),
        conn=conn,
    )


def index_documents(docs: Iterable[Document], conn: sqlite3.Connection | None = None) -> list[int]:
    db, owned = _open(conn)
    try:
        ids = [index_document(doc, conn=db) for doc in docs]
        if owned:
            db.commit()
        return ids
    finally:
        if owned:
            db.close()


def page_count(conn: sqlite3.Connection | None = None) -> int:
    db, owned = _open(conn)
    try:
        row = db.execute("SELECT COUNT(*) AS n FROM pages").fetchone()
        return int(row["n"]) if row else 0
    finally:
        if owned:
            db.close()
