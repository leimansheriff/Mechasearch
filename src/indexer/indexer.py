"""Full-text indexing module using Whoosh."""

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Union, Optional
from whoosh import index
from whoosh.index import Index

from config import settings
from src.indexer.schema import create_search_schema
from src.indexer.topics import classify_topics
from src.storage.db import DatabaseManager
from src.storage.models import PageRecord


@dataclass
class IndexReport:
    """Summary of an indexing execution run."""
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    total_pages: int = 0
    unclassified: int = 0


class SearchIndexer:
    """Manages the creation, rebuilding, and updating of the Whoosh search index."""

    def __init__(self, index_dir: Optional[Union[str, Path]] = None):
        self.index_dir = Path(index_dir or settings.INDEX_DIR)

    def _ensure_dir(self, clean: bool = False) -> None:
        """Prepares the target index directory on disk."""
        if clean and self.index_dir.exists():
            shutil.rmtree(self.index_dir, ignore_errors=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def open_or_create_index(self, clean: bool = False) -> Index:
        """
        Opens an existing Whoosh index or creates a fresh one.
        If clean=True, any existing index files in the directory are wiped first.
        """
        self._ensure_dir(clean=clean)
        schema = create_search_schema()
        if clean or not index.exists_in(str(self.index_dir)):
            return index.create_in(str(self.index_dir), schema)
        return index.open_dir(str(self.index_dir))

    def is_eligible_page(self, page: PageRecord) -> bool:
        """
        Determines if a page record is eligible for indexing.
        Requires HTTP 200, valid URL, and non-empty extracted text.
        """
        if not page or not page.url:
            return False
        if page.http_status != 200:
            return False
        if not page.content_text or not page.content_text.strip():
            return False
        return True

    def build_from_pages(self, pages: List[PageRecord], clean: bool = True) -> IndexReport:
        """
        Indexes a list of PageRecord objects into the Whoosh index.
        Safely handles duplicate URLs and empty collections.
        """
        report = IndexReport(total_pages=len(pages))
        ix = self.open_or_create_index(clean=clean)
        writer = ix.writer()

        seen_urls = set()

        try:
            for page in pages:
                if not self.is_eligible_page(page):
                    report.skipped += 1
                    continue

                if page.url in seen_urls:
                    report.skipped += 1
                    continue

                try:
                    title_clean = (page.title or "Untitled").strip()
                    content_clean = page.content_text.strip()
                    crawled_at_clean = page.crawled_at or ""

                    # Topic labels come from the page's own title, text and URL via
                    # the deterministic rules in src.indexer.topics. They are stored
                    # for filtering and display only and never affect ranking.
                    topics = classify_topics(
                        page.title, page.content_text, page.url
                    )
                    if not topics:
                        report.unclassified += 1

                    # update_document replaces existing documents with the same unique key (url)
                    writer.update_document(
                        url=page.url,
                        domain=page.domain,
                        title=title_clean,
                        content=content_clean,
                        crawled_at=crawled_at_clean,
                        topics=",".join(topics),
                    )
                    seen_urls.add(page.url)
                    report.indexed += 1
                except Exception:
                    report.failed += 1

            writer.commit()
        except Exception:
            writer.cancel()
            raise
        finally:
            ix.close()

        return report

    def build_from_database(
        self, db_manager: DatabaseManager, clean: bool = True
    ) -> IndexReport:
        """
        Loads all stored pages from the SQLite database and indexes them.
        Keeps database access and indexing logic strictly decoupled.
        """
        pages = db_manager.get_all_pages()
        return self.build_from_pages(pages, clean=clean)
