"""HTTP fetching with timeouts, a descriptive User-Agent, and graceful errors."""

from dataclasses import dataclass
from typing import Optional

import requests

from config import settings


@dataclass
class FetchResult:
    """Outcome of one HTTP request.

    ``html`` is populated only for successful HTML responses. ``error`` carries
    a short human-readable reason for every failure so the crawler can log it
    without raising exceptions into the crawl loop.
    """

    url: str
    status_code: Optional[int]
    html: Optional[str] = None
    content_type: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return (
            self.error is None
            and self.html is not None
            and self.status_code is not None
            and 200 <= self.status_code < 300
        )


class Fetcher:
    """Fetches HTML pages politely and converts failures into FetchResult."""

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        user_agent: str = settings.USER_AGENT,
        timeout: float = settings.REQUEST_TIMEOUT,
        max_content_length: int = settings.MAX_CONTENT_LENGTH,
    ):
        self.session = session or requests.Session()
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_content_length = max_content_length
        self.request_headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        }

    def fetch(self, url: str) -> FetchResult:
        """Fetch one URL, following redirects and returning the final URL.

        Network errors, timeouts, non-2xx statuses, non-HTML content types and
        oversized responses are returned as failed FetchResults rather than
        raised, so one bad page cannot stop a crawl.
        """
        try:
            response = self.session.get(
                url,
                headers=self.request_headers,
                timeout=self.timeout,
                allow_redirects=True,
                stream=True,
            )
        except requests.Timeout:
            return FetchResult(
                url=url,
                status_code=None,
                error=f"Request timed out after {self.timeout:g}s",
            )
        except requests.RequestException as exc:
            return FetchResult(
                url=url,
                status_code=None,
                error=f"Request failed: {exc}",
            )

        try:
            final_url = response.url or url
            status = response.status_code

            if not 200 <= status < 300:
                return FetchResult(
                    url=final_url,
                    status_code=status,
                    error=f"HTTP {status}",
                )

            content_type = response.headers.get("Content-Type", "")
            if content_type and not any(
                media_type in content_type.lower()
                for media_type in ("text/html", "application/xhtml+xml")
            ):
                return FetchResult(
                    url=final_url,
                    status_code=status,
                    content_type=content_type,
                    error=f"Unsupported content type: {content_type}",
                )

            declared_length = response.headers.get("Content-Length")
            if declared_length and declared_length.isdigit():
                if int(declared_length) > self.max_content_length:
                    return FetchResult(
                        url=final_url,
                        status_code=status,
                        content_type=content_type,
                        error=(
                            "Response exceeds maximum size of "
                            f"{self.max_content_length} bytes"
                        ),
                    )

            body = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                body.extend(chunk)
                if len(body) > self.max_content_length:
                    return FetchResult(
                        url=final_url,
                        status_code=status,
                        content_type=content_type,
                        error=(
                            "Response exceeds maximum size of "
                            f"{self.max_content_length} bytes"
                        ),
                    )

            encoding = response.encoding or "utf-8"
            try:
                html = bytes(body).decode(encoding, errors="replace")
            except LookupError:
                html = bytes(body).decode("utf-8", errors="replace")

            return FetchResult(
                url=final_url,
                status_code=status,
                html=html,
                content_type=content_type or None,
            )

        except requests.Timeout:
            return FetchResult(
                url=response.url or url,
                status_code=None,
                error=f"Request timed out after {self.timeout:g}s",
            )
        except requests.RequestException as exc:
            return FetchResult(
                url=response.url or url,
                status_code=None,
                error=f"Request failed while reading response: {exc}",
            )
        finally:
            response.close()
