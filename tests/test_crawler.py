"""Integration tests for the crawler using mocked HTTP responses."""

import requests

from src.crawler.crawler import Crawler
from src.crawler.fetcher import Fetcher
from src.storage.db import DatabaseManager
from tests.http_fakes import FakeResponse, FakeSession

ALLOWED = ["docs.arduino.cc"]
SEED = "https://docs.arduino.cc/learn/"
SECOND = "https://docs.arduino.cc/learn/b"
THIRD = "https://docs.arduino.cc/learn/c"


class FakePoliteness:
    """Stands in for PolitenessManager without touching the network."""

    def __init__(self, disallowed=()):
        self.disallowed = set(disallowed)
        self.checked = []
        self.delayed = []

    def can_fetch(self, url):
        self.checked.append(url)
        return url not in self.disallowed

    def enforce_delay(self, url):
        self.delayed.append(url)
        return 0.0


def make_crawler(tmp_path, routes, seeds=None, max_pages=10, max_depth=3, disallowed=()):
    db = DatabaseManager(tmp_path / "pages.db")
    session = FakeSession(routes)
    politeness = FakePoliteness(disallowed)
    crawler = Crawler(
        db=db,
        allowed_domains=ALLOWED,
        seed_urls=seeds if seeds is not None else [SEED],
        max_pages=max_pages,
        max_depth=max_depth,
        fetcher=Fetcher(session=session),
        politeness=politeness,
    )
    return crawler, db, session, politeness


def test_crawler_saves_page_with_title_text_and_timestamp(tmp_path):
    html = """
    <html><head><title>Arduino Electronics</title></head>
    <body><p>Visible course text.</p></body></html>
    """
    crawler, db, session, politeness = make_crawler(
        tmp_path, {SEED: FakeResponse(url=SEED, content=html)}
    )

    stats = crawler.crawl()

    assert stats.pages_fetched == 1
    assert stats.pages_saved == 1
    assert stats.errors == 0
    assert session.calls == [SEED]
    # Checked before fetching and again for the post-redirect final URL.
    assert politeness.checked[0] == SEED
    assert set(politeness.checked) == {SEED}

    pages = db.get_all_pages()
    assert len(pages) == 1
    page = pages[0]
    assert page.url == SEED
    assert page.domain == "docs.arduino.cc"
    assert page.title == "Arduino Electronics"
    assert page.content_text == "Visible course text."
    assert page.http_status == 200
    assert page.content_length == len("Visible course text.")
    assert page.crawled_at  # persisted crawl timestamp


def test_crawler_normalizes_and_deduplicates_links(tmp_path):
    html = """
    <html><head><title>Seed</title></head><body>
      <a href="b">B</a>
      <a href="b#details">B with fragment</a>
      <a href="b?utm_source=newsletter">B with tracking</a>
      <a href="https://docs.arduino.cc/learn/b">B absolute</a>
    </body></html>
    """
    routes = {
        SEED: FakeResponse(url=SEED, content=html),
        SECOND: FakeResponse(url=SECOND, content="<html><title>B</title><body>B</body></html>"),
    }
    crawler, db, session, _ = make_crawler(tmp_path, routes)

    stats = crawler.crawl()

    assert session.calls == [SEED, SECOND]
    assert stats.pages_saved == 2
    assert db.get_page_count() == 2


def test_crawler_rejects_links_outside_approved_domains(tmp_path):
    html = """
    <html><head><title>Seed</title></head><body>
      <a href="https://malicious.example/hack">External</a>
      <a href="https://docs.arduino.cc/files/manual.pdf">PDF</a>
      <a href="https://docs.arduino.cc/learn/b">Approved</a>
    </body></html>
    """
    routes = {
        SEED: FakeResponse(url=SEED, content=html),
        SECOND: FakeResponse(url=SECOND, content="<html><body>B</body></html>"),
    }
    crawler, db, session, _ = make_crawler(tmp_path, routes)

    stats = crawler.crawl()

    assert session.calls == [SEED, SECOND]
    assert "https://malicious.example/hack" not in session.calls
    assert db.get_page_count() == 2


def test_crawler_rejects_unapproved_seed(tmp_path):
    crawler, db, session, _ = make_crawler(
        tmp_path,
        {},
        seeds=["https://malicious.example/"],
    )

    stats = crawler.crawl()

    assert session.calls == []
    assert stats.pages_fetched == 0
    assert db.get_page_count() == 0


def test_crawler_respects_robots_txt_disallow(tmp_path):
    crawler, db, session, _ = make_crawler(
        tmp_path,
        {},
        disallowed={SEED},
    )

    stats = crawler.crawl()

    assert session.calls == []
    assert stats.blocked == 1
    assert db.get_page_count() == 0

    with db._get_connection() as conn:
        row = conn.execute(
            "SELECT url, status_code, error_message FROM crawl_log"
        ).fetchone()
    assert row["url"] == SEED
    assert row["status_code"] is None
    assert row["error_message"] == "Blocked by robots.txt"


def test_crawler_handles_http_errors_and_timeouts(tmp_path):
    routes = {
        SEED: FakeResponse(url=SEED, status_code=500, content=b"server error"),
        SECOND: requests.Timeout("simulated timeout"),
    }
    crawler, db, session, _ = make_crawler(tmp_path, routes, seeds=[SEED, SECOND])

    stats = crawler.crawl()

    assert session.calls == [SEED, SECOND]
    assert stats.pages_fetched == 2
    assert stats.errors == 2
    assert stats.pages_saved == 0
    assert db.get_page_count() == 0

    with db._get_connection() as conn:
        rows = conn.execute(
            "SELECT url, status_code, error_message FROM crawl_log ORDER BY id"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["status_code"] == 500
    assert rows[1]["status_code"] is None
    assert "timed out" in rows[1]["error_message"]


def test_crawler_stops_at_max_pages(tmp_path):
    html = """
    <html><head><title>Seed</title></head><body>
      <a href="b">B</a><a href="c">C</a>
    </body></html>
    """
    routes = {
        SEED: FakeResponse(url=SEED, content=html),
        SECOND: FakeResponse(url=SECOND, content="<html><body>B</body></html>"),
        THIRD: FakeResponse(url=THIRD, content="<html><body>C</body></html>"),
    }
    crawler, db, session, _ = make_crawler(tmp_path, routes, max_pages=2)

    stats = crawler.crawl()

    assert stats.pages_fetched == 2
    assert len(session.calls) == 2
    assert session.calls[0] == SEED
    assert db.get_page_count() == 2


def test_crawler_uses_canonical_url_and_does_not_refetch_it(tmp_path):
    canonical = "https://docs.arduino.cc/learn/canonical"
    html = """
    <html>
      <head>
        <title>Canonical Page</title>
        <link rel="canonical" href="canonical#top">
      </head>
      <body>
        <p>Canonical body.</p>
        <a href="canonical">Self canonical link</a>
      </body>
    </html>
    """
    routes = {SEED: FakeResponse(url=SEED, content=html)}
    crawler, db, session, _ = make_crawler(tmp_path, routes)

    stats = crawler.crawl()

    assert session.calls == [SEED]
    assert stats.pages_saved == 1
    pages = db.get_all_pages()
    assert len(pages) == 1
    assert pages[0].url == canonical


def test_crawler_rejects_redirect_outside_approved_scope(tmp_path):
    html = "<html><head><title>Offsite</title></head><body>Offsite</body></html>"
    routes = {
        SEED: FakeResponse(url="https://malicious.example/landing", content=html)
    }
    crawler, db, session, _ = make_crawler(tmp_path, routes)

    stats = crawler.crawl()

    assert session.calls == [SEED]
    assert stats.rejected == 1
    assert stats.pages_saved == 0
    assert db.get_page_count() == 0
