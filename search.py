from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass

from db import connect, init_db
from tokens import tokenize

SNIPPET_RADIUS = 80


@dataclass
class SearchHit:
    url: str
    title: str
    snippet: str
    score: float
    repo_name: str = ""
    file_path: str = ""
    language: str = ""


def search(
    query: str,
    limit: int = 20,
    conn: sqlite3.Connection | None = None,
) -> list[SearchHit]:
    terms = tokenize(query)
    if not terms:
        return []

    owned = conn is None
    if owned:
        conn = connect()
        init_db(conn)
    assert conn is not None
    try:
        n_row = conn.execute("SELECT COUNT(*) AS n FROM pages").fetchone()
        n_docs = int(n_row["n"]) if n_row else 0
        if n_docs == 0:
            return []

        placeholders = ",".join("?" * len(terms))
        df_rows = conn.execute(
            f"SELECT term, COUNT(DISTINCT page_id) AS df FROM postings WHERE term IN ({placeholders}) GROUP BY term",
            terms,
        ).fetchall()
        df = {row["term"]: int(row["df"]) for row in df_rows}

        postings, doc_lengths = _lookup_postings(conn, terms)
        if not postings:
            return []

        scores = _bm25_scores(terms, postings, doc_lengths, n_docs, df)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]
        if not ranked:
            return []

        ids = [page_id for page_id, _ in ranked]
        id_placeholders = ",".join("?" * len(ids))
        page_rows = conn.execute(
            f"""
            SELECT id, url, title, text, repo_name, file_path, language
            FROM pages WHERE id IN ({id_placeholders})
            """,
            ids,
        ).fetchall()
        pages = {int(row["id"]): row for row in page_rows}

        hits: list[SearchHit] = []
        for page_id, score in ranked:
            page = pages[page_id]
            hits.append(
                SearchHit(
                    url=page["url"],
                    title=page["title"] or page["url"],
                    snippet=_snippet(page["text"], terms),
                    score=round(score, 4),
                    repo_name=page["repo_name"] or "",
                    file_path=page["file_path"] or "",
                    language=page["language"] or "",
                )
            )
        return hits
    finally:
        if owned:
            conn.close()


def _lookup_postings(
    conn: sqlite3.Connection,
    terms: list[str],
) -> tuple[list[sqlite3.Row], dict[int, int]]:
    """Read the inverted index: which documents contain the query terms, and each doc's length."""
    placeholders = ",".join("?" * len(terms))
    posting_rows = conn.execute(
        f"SELECT page_id, term, tf FROM postings WHERE term IN ({placeholders})",
        terms,
    ).fetchall()
    if not posting_rows:
        return [], {}

    lengths = {
        int(row["page_id"]): int(row["dl"])
        for row in conn.execute("SELECT page_id, SUM(tf) AS dl FROM postings GROUP BY page_id")
    }
    return posting_rows, lengths


def _bm25_scores(
    terms: list[str],
    postings: list[sqlite3.Row],
    lengths: dict[int, int],
    n_docs: int,
    df: dict[str, int],
    k1: float = 1.2,
    b: float = 0.75,
) -> dict[int, float]:
    """Existing ranking. Kept as-is so current search behavior does not change."""
    idf = {
        term: math.log((n_docs - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5) + 1.0)
        for term in terms
    }
    avgdl = (sum(lengths.values()) / len(lengths)) if lengths else 1.0

    scores: dict[int, float] = {}
    for row in postings:
        page_id = int(row["page_id"])
        tf = int(row["tf"])
        dl = lengths.get(page_id, 1)
        denom = tf + k1 * (1 - b + b * dl / avgdl)
        scores[page_id] = scores.get(page_id, 0.0) + idf[row["term"]] * (tf * (k1 + 1) / denom)
    return scores


def _snippet(text: str, terms: list[str]) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if not compact:
        return ""
    lower = compact.lower()
    pos = min((lower.find(term) for term in terms if term in lower), default=-1)
    if pos < 0:
        return compact[:160]
    start = max(0, pos - SNIPPET_RADIUS)
    end = min(len(compact), pos + SNIPPET_RADIUS)
    snippet = compact[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(compact):
        snippet = snippet + "…"
    return snippet
