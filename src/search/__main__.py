"""Command-line interface to search the mechatronics index from the terminal."""

import argparse
import sys
import time
from pathlib import Path

from config import settings
from src.search.searcher import SearchEngine


def main() -> None:
    # Page text can contain characters the Windows console cannot encode.
    # Replace them instead of crashing while printing a snippet.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(
        description="Search the mechatronics full-text index from the command line."
    )
    parser.add_argument(
        "query",
        type=str,
        help="Search query text (e.g. 'PID controller', 'stepper motor', 'PLC automation')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of results to return (default: 5)",
    )
    parser.add_argument(
        "--index-dir",
        type=str,
        default=str(settings.INDEX_DIR),
        help=f"Path to Whoosh index directory (default: {settings.INDEX_DIR})",
    )

    args = parser.parse_args()

    engine = SearchEngine(index_dir=args.index_dir)
    if not engine.is_index_ready():
        print(f"Error: Search index not found or uninitialized at '{args.index_dir}'.", file=sys.stderr)
        print("Please build the index first using: python -m src.indexer", file=sys.stderr)
        sys.exit(1)

    start_time = time.perf_counter()
    with engine:
        results = engine.search(query_text=args.query, limit=args.limit)
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    print(f"\nSearch results for: \"{args.query}\"")
    print(f"Matched {len(results)} document(s) in {elapsed_ms:.2f} ms\n" + "=" * 60)

    if not results:
        print("No matching mechatronics documents found.")
        print(
            "Every query term must appear somewhere in the indexed collection; "
            "try broader terms like 'motor', 'sensor', or 'control'."
        )
        return

    for idx, res in enumerate(results, start=1):
        print(f"\n[{idx}] {res.title}")
        print(f"    URL:    {res.url}")
        print(f"    Domain: {res.domain} | BM25F Score: {res.score:.3f}")
        # Snippets are already plain text (markup stripped by SearchEngine).
        print(f"    Snippet: {res.snippet}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
