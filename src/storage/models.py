"""Data models for stored pages and search results."""

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass
class PageRecord:
    """Represents a crawled and parsed mechatronics web page stored in SQLite."""
    url: str
    domain: str
    title: str
    content_text: str
    http_status: int
    content_length: int
    crawled_at: Optional[str] = None


@dataclass
class SearchResult:
    """Represents a ranked document result returned to the user or UI.

    ``topics`` carries the topic slugs assigned to the page at index time by
    ``src.indexer.topics.classify_topics``. It defaults to an empty tuple so the
    field is optional for callers that build a SearchResult by hand.
    """
    url: str
    title: str
    snippet: str
    score: float
    domain: str
    topics: Tuple[str, ...] = field(default_factory=tuple)
