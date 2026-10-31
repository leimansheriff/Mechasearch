"""Small in-memory fakes for the requests.Session HTTP boundary."""

import requests


class FakeResponse:
    def __init__(self, url, status_code=200, content=b"", headers=None, encoding="utf-8"):
        self.url = url
        self.status_code = status_code
        self.content = content if isinstance(content, bytes) else content.encode("utf-8")
        self.headers = (
            {"Content-Type": "text/html; charset=utf-8"}
            if headers is None
            else headers
        )
        self.encoding = encoding
        self.closed = False

    @property
    def text(self):
        return self.content.decode(self.encoding or "utf-8", errors="replace")

    def iter_content(self, chunk_size=8192):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start:start + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    """Minimal stand-in for requests.Session.

    ``routes`` maps an exact URL to a FakeResponse, a RequestException
    instance (raised on request), or a zero-argument callable returning either.
    """

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []
        self.last_kwargs = None
        self.headers = {}

    def get(self, url, **kwargs):
        self.calls.append(url)
        self.last_kwargs = kwargs

        if url not in self.routes:
            raise requests.ConnectionError(f"No fake route registered for {url}")

        route = self.routes[url]
        if callable(route):
            route = route()
        if isinstance(route, Exception):
            raise route
        return route
