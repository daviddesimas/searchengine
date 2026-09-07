from __future__ import annotations

import argparse

from crawler import crawl
from github import fetch_repo_files
from indexer import index_documents, page_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Local search engine")
    sub = parser.add_subparsers(dest="cmd", required=True)

    crawl_p = sub.add_parser("crawl", help="Crawl a seed URL and add pages to the index")
    crawl_p.add_argument("url")
    crawl_p.add_argument("--max-pages", type=int, default=20)

    github_p = sub.add_parser("github", help="Fetch files from a GitHub repo and add them to the index")
    github_p.add_argument("repo", help="owner/repo or https://github.com/owner/repo")
    github_p.add_argument("--max-files", type=int, default=50)

    sub.add_parser("serve", help="Start the search UI")
    sub.add_parser("stats", help="Show how many documents are indexed")

    args = parser.parse_args()
    if args.cmd == "crawl":
        result = crawl(args.url, max_pages=args.max_pages)
        if result["count"] == 0:
            detail = result.get("error") or f"{result['skipped']} skipped"
            print(f"Crawl failed: no pages indexed. {detail}")
        else:
            print(f"Indexed {result['count']} pages ({result['skipped']} skipped)")
            for url in result["crawled"]:
                print(f"  {url}")
    elif args.cmd == "github":
        docs = fetch_repo_files(args.repo, max_files=max(1, args.max_files))
        ids = index_documents(docs)
        print(f"Indexed {len(ids)} files from {args.repo}")
        for doc in docs:
            print(f"  {doc.file_path}")
    elif args.cmd == "stats":
        print(f"{page_count()} documents in the index")
    elif args.cmd == "serve":
        import uvicorn

        uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
