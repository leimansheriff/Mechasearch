"""Storage package for SQLite database operations and models."""

from src.storage.models import PageRecord, SearchResult
from src.storage.db import DatabaseManager

__all__ = ["PageRecord", "SearchResult", "DatabaseManager"]
