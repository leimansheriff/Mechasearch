"""SQLite database management for crawled pages and crawl logs."""

import sqlite3
from pathlib import Path
from typing import Optional, List, Union
from src.storage.models import PageRecord


class DatabaseManager:
    """Manages SQLite connections, schema initialization, and page persistence."""

    def __init__(self, db_path: Union[str, Path]):
        self.db_path = str(db_path)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Returns a configured SQLite connection."""
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initializes the database tables and primary constraints."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Primary table for storing pages (url is unique primary key)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pages (
                    url TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    title TEXT,
                    content_text TEXT NOT NULL,
                    http_status INTEGER NOT NULL,
                    content_length INTEGER NOT NULL,
                    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Audit log for crawl attempts, status codes, and network errors
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS crawl_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    status_code INTEGER,
                    error_message TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

    def save_page(self, page: PageRecord) -> bool:
        """
        Inserts a crawled page. Returns True if successfully inserted,
        or False if the URL was already present.
        """
        query = """
            INSERT OR IGNORE INTO pages (
                url, domain, title, content_text, http_status, content_length, crawled_at
            )
            VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                query,
                (
                    page.url,
                    page.domain,
                    page.title,
                    page.content_text,
                    page.http_status,
                    page.content_length,
                    page.crawled_at,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def has_url(self, url: str) -> bool:
        """Checks if a URL has already been crawled and stored."""
        query = "SELECT 1 FROM pages WHERE url = ? LIMIT 1"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (url,))
            return cursor.fetchone() is not None

    def get_page_count(self) -> int:
        """Returns the total number of stored pages."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM pages")
            row = cursor.fetchone()
            return row[0] if row else 0

    def get_all_pages(self) -> List[PageRecord]:
        """Loads all stored pages from SQLite, typically for indexing."""
        query = "SELECT url, domain, title, content_text, http_status, content_length, crawled_at FROM pages"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            return [
                PageRecord(
                    url=row["url"],
                    domain=row["domain"],
                    title=row["title"],
                    content_text=row["content_text"],
                    http_status=row["http_status"],
                    content_length=row["content_length"],
                    crawled_at=str(row["crawled_at"]),
                )
                for row in rows
            ]

    def log_crawl_attempt(
        self, url: str, status_code: Optional[int] = None, error_message: Optional[str] = None
    ) -> None:
        """Records an HTTP crawl outcome or error into crawl_log."""
        query = """
            INSERT INTO crawl_log (url, status_code, error_message)
            VALUES (?, ?, ?)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (url, status_code, error_message))
            conn.commit()
