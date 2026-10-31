"""Unit tests for HTTP fetching with mocked responses (no internet access)."""

import requests

from config import settings
from src.crawler.fetcher import Fetcher
from tests.http_fakes import FakeResponse, FakeSession

URL = "https://docs.arduino.cc/learn/electronics/"


def test_fetch_success_returns_html_and_final_url():
    session = FakeSession({
        URL: FakeResponse(
            url=URL,
            content=b"<html><head><title>Arduino</title></head><body>Hi</body></html>",
        )
    })
    fetcher = Fetcher(session=session)

    result = fetcher.fetch(URL)

    assert result.ok is True
    assert result.status_code == 200
    assert result.url == URL
    assert "<title>Arduino</title>" in result.html
    assert result.error is None
    # The descriptive User-Agent and timeout are always sent.
    sent_headers = session.last_kwargs["headers"]
    assert sent_headers["User-Agent"] == settings.USER_AGENT
    assert session.last_kwargs["timeout"] == settings.REQUEST_TIMEOUT


def test_fetch_http_error_is_returned_not_raised():
    session = FakeSession({
        URL: FakeResponse(url=URL, status_code=404, content=b"not found")
    })
    result = Fetcher(session=session).fetch(URL)

    assert result.ok is False
    assert result.status_code == 404
    assert result.error == "HTTP 404"
    assert result.html is None


def test_fetch_timeout_is_handled_gracefully():
    session = FakeSession({URL: requests.Timeout("simulated timeout")})

    result = Fetcher(session=session, timeout=1.5).fetch(URL)

    assert result.ok is False
    assert result.status_code is None
    assert "timed out" in result.error


def test_fetch_connection_error_is_handled_gracefully():
    session = FakeSession({URL: requests.ConnectionError("connection refused")})

    result = Fetcher(session=session).fetch(URL)

    assert result.ok is False
    assert result.status_code is None
    assert "Request failed" in result.error


def test_fetch_rejects_non_html_content():
    session = FakeSession({
        URL: FakeResponse(
            url=URL,
            headers={"Content-Type": "application/pdf"},
            content=b"%PDF-1.7",
        )
    })

    result = Fetcher(session=session).fetch(URL)

    assert result.ok is False
    assert "Unsupported content type" in result.error


def test_fetch_enforces_max_content_length():
    session = FakeSession({
        URL: FakeResponse(url=URL, content=b"<html>" + (b"x" * 500) + b"</html>")
    })

    result = Fetcher(session=session, max_content_length=100).fetch(URL)

    assert result.ok is False
    assert "maximum size" in result.error
    assert session.calls == [URL]
