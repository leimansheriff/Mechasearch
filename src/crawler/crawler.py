"""Breadth-first crawler: approved domains, robots.txt, limits and SQLite storage."""

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional
from urllib.parse import urlparse

from config import settings
from src.crawler.extractor import extract_page
from src.crawler.fetcher import Fetcher
from src.crawler.politeness import PolitenessManager
from src.crawler.url_safety import URLSafety
from src.storage.db import DatabaseManager
from src.storage.models import PageRecord


@dataclass
class CrawlStats:
    """Counters describing what happened during one crawl run."""

    pages_fetched: int = 0
    pages_saved: int = 0
    duplicates: int = 0
    errors: int = 0
    blocked: int = 0
    rejected: int = 0


def _utc_now_iso() -> str:
    """Returns the current UTC crawl timestamp in ISO 8601 form."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Crawler:
    """Crawls approved domains breadth-first and stores parsed pages in SQLite.

    Safety properties:
    * Seeds and discovered links must pass the domain allowlist.
    * robots.txt is checked before every fetch.
    * Per-domain crawl delay is enforced.
    * Every normalized URL is enqueued at most once.
    * Fetching stops at ``max_pages`` attempts and ``max_depth`` link hops.
    """

    def __init__(
        self,
        db: DatabaseManager,
        allowed_domains: Optional[Iterable[str]] = None,
        seed_urls: Optional[Iterable[str]] = None,
        max_pages: Optional[int] = None,
        max_depth: Optional[int] = None,
        fetcher: Optional[Fetcher] = None,
        politeness: Optional[PolitenessManager] = None,
        user_agent: str = settings.USER_AGENT,
        default_delay: float = settings.DEFAULT_CRAWL_DELAY,
        timeout: float = settings.REQUEST_TIMEOUT,
    ):
        self.db = db
        self.allowed_domains = list(
            allowed_domains if allowed_domains is not None else settings.ALLOWED_DOMAINS
        )
        self.seed_urls = list(
            seed_urls if seed_urls is not None else settings.SEED_URLS
        )
        self.max_pages = (
            settings.MAX_PAGES_TO_CRAWL if max_pages is None else max_pages
        )
        self.max_depth = (
            settings.MAX_CRAWL_DEPTH if max_depth is None else max_depth
        )
        self.fetcher = fetcher or Fetcher(user_agent=user_agent, timeout=timeout)
        self.politeness = politeness or PolitenessManager(
            user_agent=user_agent,
            default_delay=default_delay,
            request_timeout=timeout,
        )

    def _is_crawlable(self, url: str) -> bool:
        """True when a normalized URL is on an approved domain and is HTML-like."""
        return (
            URLSafety.is_allowed_domain(url, self.allowed_domains)
            and not URLSafety.has_ignored_extension(url)
        )

    def _seed_queue(self, seeds: Iterable[str]) -> deque:
        """Normalizes and validates seeds, returning a queue of (url, depth)."""
        queue = deque()
        seen = set()

        for raw_seed in seeds:
            normalized = URLSafety.normalize_url(raw_seed)
            if not normalized or not self._is_crawlable(normalized):
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            queue.append((normalized, 0))

        return queue

    def crawl(self, seeds: Optional[Iterable[str]] = None) -> CrawlStats:
        """Run the crawl and return counters for the run."""
        stats = CrawlStats()
        queue = self._seed_queue(self.seed_urls if seeds is None else seeds)
        seen = {url for url, _ in queue}

        while queue and stats.pages_fetched < self.max_pages:
            url, depth = queue.popleft()

            if depth > self.max_depth:
                continue

            if not self._is_crawlable(url):
                stats.rejected += 1
                continue

            # robots.txt must be consulted before any page request.
            if not self.politeness.can_fetch(url):
                stats.blocked += 1
                self.db.log_crawl_attempt(
                    url, error_message="Blocked by robots.txt"
                )
                continue

            self.politeness.enforce_delay(url)
            result = self.fetcher.fetch(url)
            stats.pages_fetched += 1

            if not result.ok:
                stats.errors += 1
                self.db.log_crawl_attempt(
                    url,
                    status_code=result.status_code,
                    error_message=result.error,
                )
                continue

            # A redirect may leave the allowlist; never store such a page.
            final_url = URLSafety.normalize_url(result.url)
            if (
                not final_url
                or not self._is_crawlable(final_url)
                or not self.politeness.can_fetch(final_url)
            ):
                stats.rejected += 1
                self.db.log_crawl_attempt(
                    url,
                    status_code=result.status_code,
                    error_message="Redirected outside approved crawl scope",
                )
                continue

            page = extract_page(result.html, final_url)

            # Prefer the declared canonical URL when it is safe to store.
            canonical_url = None
            if page.canonical_url:
                canonical_url = URLSafety.normalize_url(
                    page.canonical_url, base_url=final_url
                )
            if canonical_url and self._is_crawlable(canonical_url):
                store_url = canonical_url
            else:
                store_url = final_url

            record = PageRecord(
                url=store_url,
                domain=urlparse(store_url).netloc.lower(),
                title=page.title,
                content_text=page.text,
                http_status=result.status_code,
                content_length=len(page.text),
                crawled_at=_utc_now_iso(),
            )

            if self.db.save_page(record):
                stats.pages_saved += 1
            else:
                stats.duplicates += 1

            seen.add(store_url)
            self.db.log_crawl_attempt(url, status_code=result.status_code)

            if depth >= self.max_depth:
                continue

            for link in page.links:
                normalized = URLSafety.normalize_url(link, base_url=final_url)
                if not normalized or normalized in seen:
                    continue
                if not self._is_crawlable(normalized):
                    continue
                seen.add(normalized)
                queue.append((normalized, depth + 1))

        return stats


def build_arg_parser() -> argparse.ArgumentParser:
    """Builds the CLI parser for the approved-site crawler."""
    parser = argparse.ArgumentParser(
        prog="python -m src.crawler",
        description=(
            "Crawl explicitly approved domains only. Seed URLs must be on "
            "config.settings.ALLOWED_DOMAINS."
        ),
    )
    parser.add_argument(
        "--seed",
        dest="seeds",
        action="append",
        help=(
            "Seed URL; repeat for multiple seeds. Defaults to "
            "config.settings.SEED_URLS. Must be on an approved domain."
        ),
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=settings.MAX_PAGES_TO_CRAWL,
        help="Maximum number of page fetch attempts (default: %(default)s).",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=settings.MAX_CRAWL_DEPTH,
        help="Maximum link depth from a seed (default: %(default)s).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=settings.DEFAULT_CRAWL_DELAY,
        help="Seconds between requests to a host (default: %(default)s).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=settings.REQUEST_TIMEOUT,
        help="HTTP timeout in seconds (default: %(default)s).",
    )
    parser.add_argument(
        "--db",
        default=str(settings.DB_PATH),
        help="SQLite database path (default: %(default)s).",
    )
    return parser


def main(argv=None) -> int:
    """CLI entry point: validate seeds, crawl, print a summary."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.max_pages < 1:
        parser.error("--max-pages must be at least 1")
    if args.max_depth < 0:
        parser.error("--max-depth must be zero or greater")

    seeds = args.seeds if args.seeds is not None else list(settings.SEED_URLS)
    for seed in seeds:
        normalized = URLSafety.normalize_url(seed)
        if not normalized or not URLSafety.is_allowed_domain(
            normalized, settings.ALLOWED_DOMAINS
        ):
            parser.error(f"Seed URL is not on an approved domain: {seed}")

    db = DatabaseManager(args.db)
    crawler = Crawler(
        db=db,
        allowed_domains=settings.ALLOWED_DOMAINS,
        seed_urls=seeds,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        fetcher=Fetcher(user_agent=settings.USER_AGENT, timeout=args.timeout),
        politeness=PolitenessManager(
            user_agent=settings.USER_AGENT,
            default_delay=args.delay,
            request_timeout=args.timeout,
        ),
    )

    stats = crawler.crawl()

    print(f"Fetched: {stats.pages_fetched}")
    print(f"Saved:   {stats.pages_saved}")
    print(f"Duplicates ignored: {stats.duplicates}")
    print(f"Errors:  {stats.errors}")
    print(f"Blocked by robots.txt: {stats.blocked}")
    print(f"Rejected outside scope: {stats.rejected}")
    print(f"Database: {args.db}")
    return 0
