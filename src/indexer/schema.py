"""Whoosh schema definition for Mechatronics Search Engine."""

from whoosh.fields import Schema, ID, KEYWORD, TEXT, STORED
from whoosh.analysis import StemmingAnalyzer


def create_search_schema() -> Schema:
    """
    Creates and returns the Whoosh schema for indexing mechatronics documents.
    
    Fields:
    - url: Unique document identifier, stored for display and deduplication.
    - domain: Host domain (e.g., 'docs.arduino.cc'), stored for filtering/display.
    - title: Document title, stemmed and boosted 2.5x over body content.
    - content: Full text body of the page, stemmed for morphological matching.
    - crawled_at: Timestamp of crawl, stored for metadata display.
    - topics: Comma-separated topic slugs (see src.indexer.topics), stored so the
      UI can show topic badges and filter results. Deliberately NOT part of the
      query parser's field list in src.search.searcher, so it can never
      contribute to BM25F scoring; it is only ever used as an exact filter.
    """
    analyzer = StemmingAnalyzer()
    return Schema(
        url=ID(stored=True, unique=True),
        domain=ID(stored=True),
        title=TEXT(stored=True, field_boost=2.5, analyzer=analyzer),
        content=TEXT(stored=True, analyzer=analyzer),
        crawled_at=STORED,
        topics=KEYWORD(stored=True, commas=True, lowercase=True),
    )
