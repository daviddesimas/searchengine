from __future__ import annotations

import unittest

import httpx

from crawler import _extract, _normalize
from db import connect, init_db
from documents import Document
from github import fetch_repo_files, language_for, parse_repo, should_index_path
from indexer import index_document, index_page, page_count
from search import search
from tokens import tokenize


def memory_db():
    conn = connect(":memory:")
    init_db(conn)
    return conn


class TokenizeTests(unittest.TestCase):
    def test_lowercases_and_drops_stopwords(self):
        self.assertEqual(tokenize("The Cat sat on the Mat"), ["cat", "sat", "mat"])

    def test_empty_and_short_tokens(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("a I to"), [])


class DocumentAndGithubHelperTests(unittest.TestCase):
    def test_parse_repo_from_slug_and_url(self):
        self.assertEqual(parse_repo("octocat/Hello-World"), ("octocat", "Hello-World"))
        self.assertEqual(
            parse_repo("https://github.com/octocat/Hello-World.git"),
            ("octocat", "Hello-World"),
        )

    def test_parse_repo_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            parse_repo("not-a-repo")
        with self.assertRaises(ValueError):
            parse_repo("https://gitlab.com/foo/bar")

    def test_language_and_skip_paths(self):
        self.assertEqual(language_for("src/app.py"), "python")
        self.assertFalse(should_index_path("node_modules/pkg/index.js"))
        self.assertFalse(should_index_path("photo.png"))
        self.assertTrue(should_index_path("src/app.py"))


class IndexAndSearchTests(unittest.TestCase):
    def test_index_page_and_search_finds_it(self):
        conn = memory_db()
        index_page("https://example.com/a", "Alpha page", "cats sit on mats", conn=conn)
        conn.commit()
        hits = search("cats", conn=conn)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].url, "https://example.com/a")
        self.assertEqual(hits[0].language, "html")
        self.assertIn("cats", hits[0].snippet.lower())

    def test_github_document_metadata_is_stored(self):
        conn = memory_db()
        doc = Document(
            url="https://github.com/acme/box/blob/main/src/hello.py",
            title="src/hello.py",
            text="def greet(): return 'hello world'",
            repo_name="acme/box",
            file_path="src/hello.py",
            language="python",
        )
        doc_id = index_document(doc, conn=conn)
        conn.commit()
        self.assertIsInstance(doc_id, int)
        self.assertEqual(page_count(conn), 1)
        hits = search("greet hello", conn=conn)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].repo_name, "acme/box")
        self.assertEqual(hits[0].file_path, "src/hello.py")
        self.assertEqual(hits[0].language, "python")

    def test_stopwords_only_query_returns_nothing(self):
        conn = memory_db()
        index_page("https://example.com/a", "Hello", "hello world", conn=conn)
        conn.commit()
        self.assertEqual(search("the and of", conn=conn), [])

    def test_reindex_same_url_replaces_postings(self):
        conn = memory_db()
        index_page("https://example.com/a", "One", "alpha uniquezebra", conn=conn)
        index_page("https://example.com/a", "Two", "beta", conn=conn)
        conn.commit()
        self.assertEqual(page_count(conn), 1)
        self.assertEqual(search("uniquezebra", conn=conn), [])
        self.assertEqual(len(search("beta", conn=conn)), 1)


class CrawlerExtractTests(unittest.TestCase):
    def test_normalize_adds_https(self):
        self.assertEqual(_normalize("example.com/x"), "https://example.com/x")
        self.assertEqual(_normalize("https://example.com/x#frag"), "https://example.com/x")
        self.assertEqual(_normalize("mailto:hi@x.com"), "")

    def test_extract_title_text_and_links(self):
        html = """
        <html><head><title>Docs</title></head>
        <body>
          <script>ignore me</script>
          <h1>Hello</h1>
          <p>Search engines rank documents.</p>
          <a href="/next">Next</a>
          <a href="photo.png">Skip</a>
        </body></html>
        """
        title, text, links = _extract("https://example.com/page", html)
        self.assertEqual(title, "Docs")
        self.assertIn("Search engines rank documents", text)
        self.assertNotIn("ignore me", text)
        self.assertEqual(links, ["https://example.com/next"])


class GithubFetchTests(unittest.TestCase):
    def test_fetch_repo_files_builds_documents(self):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url.endswith("/repos/acme/box"):
                return httpx.Response(200, json={"default_branch": "main"})
            if "git/trees/main" in url:
                return httpx.Response(
                    200,
                    json={
                        "tree": [
                            {"type": "blob", "path": "src/hello.py", "size": 20},
                            {"type": "blob", "path": "logo.png", "size": 10},
                            {"type": "tree", "path": "src"},
                        ]
                    },
                )
            if url.endswith("/acme/box/main/src/hello.py"):
                return httpx.Response(200, text="print('hello')\n")
            return httpx.Response(404, text="missing")

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        docs = fetch_repo_files("acme/box", max_files=10, client=client)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].repo_name, "acme/box")
        self.assertEqual(docs[0].file_path, "src/hello.py")
        self.assertEqual(docs[0].language, "python")
        self.assertIn("hello", docs[0].text)
        self.assertEqual(
            docs[0].url,
            "https://github.com/acme/box/blob/main/src/hello.py",
        )


class CrawlFailMessageTests(unittest.TestCase):
    def test_zero_pages_shows_message(self):
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from app import app

        with patch(
            "app.crawl",
            return_value={
                "crawled": [],
                "count": 0,
                "skipped": 1,
                "queued": 0,
                "error": "HTTP 403 for https://example.com",
            },
        ):
            response = TestClient(app).post(
                "/crawl",
                data={"url": "https://example.com", "max_pages": 1},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Crawl failed", response.text)
        self.assertIn("HTTP 403", response.text)

    def test_exception_shows_message(self):
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from app import app

        with patch("app.crawl", side_effect=ValueError("Need a valid http(s) seed URL")):
            response = TestClient(app).post(
                "/crawl",
                data={"url": "https://example.com", "max_pages": 1},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Crawl failed: Need a valid http(s) seed URL", response.text)


if __name__ == "__main__":
    unittest.main()
