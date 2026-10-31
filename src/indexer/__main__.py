"""Command-line interface to build or rebuild the Whoosh index from SQLite."""

import argparse
import sys
from pathlib import Path

from config import settings
from src.indexer.indexer import SearchIndexer
from src.storage.db import DatabaseManager


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build or rebuild the Whoosh full-text index from the SQLite database."
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(settings.DB_PATH),
        help=f"Path to SQLite database file (default: {settings.DB_PATH})",
    )
    parser.add_argument(
        "--index-dir",
        type=str,
        default=str(settings.INDEX_DIR),
        help=f"Directory to store Whoosh index files (default: {settings.INDEX_DIR})",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not wipe existing index; append or update documents in place.",
    )

    args = parser.parse_args()
    db_file = Path(args.db)

    if not db_file.exists():
        print(f"Error: Database file not found at '{db_file}'", file=sys.stderr)
        print("Run the crawler first to populate pages in SQLite.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading pages from database: {db_file}")
    db_manager = DatabaseManager(db_file)
    total_stored = db_manager.get_page_count()
    print(f"Found {total_stored} raw page record(s) in SQLite.")

    clean_build = not args.no_clean
    print(f"Building index at '{args.index_dir}' (clean={clean_build})...")
    
    indexer = SearchIndexer(index_dir=args.index_dir)
    report = indexer.build_from_database(db_manager, clean=clean_build)

    print("\n--- Indexing Complete ---")
    print(f"Total evaluated: {report.total_pages}")
    print(f"Indexed:        {report.indexed}")
    print(f"Skipped:        {report.skipped}")
    print(f"Failed:         {report.failed}")


if __name__ == "__main__":
    main()
