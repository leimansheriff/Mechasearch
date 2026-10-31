"""Politeness manager for robots.txt parsing and per-domain crawl delays."""

import time
import urllib.robotparser
from typing import Dict, Optional
from urllib.parse import urlparse

import requests


class PolitenessManager:
    """Handles robots.txt adherence and rate-limiting per host.

    robots.txt is fetched once per host with the same descriptive User-Agent
    and timeout used for page requests. Failure policy is deliberately
    conservative:

    * 2xx            -> parse and obey the rules.
    * 401/403/5xx    -> treat the whole host as disallowed.
    * network error  -> treat the whole host as disallowed.
    * other 4xx      -> robots.txt is unavailable, so crawling is allowed
                        (standard robot exclusion convention).
    """

    def __init__(
        self,
        user_agent: str,
        default_delay: float = 2.0,
        request_timeout: float = 5.0,
        session: Optional[requests.Session] = None,
    ):
        self.user_agent = user_agent
        self.default_delay = default_delay
        self.request_timeout = request_timeout
        self._session = session or requests.Session()
        self._parsers: Dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last_request_times: Dict[str, float] = {}

    def _get_domain(self, url: str) -> str:
        """Extracts the lowercased network location (domain) from a URL."""
        return urlparse(url).netloc.lower()

    def _load_robot_parser(self, url: str) -> urllib.robotparser.RobotFileParser:
        """Fetches and parses robots.txt for the URL's host."""
        domain = self._get_domain(url)
        scheme = urlparse(url).scheme or "https"
        robots_url = f"{scheme}://{domain}/robots.txt"

        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)

        try:
            response = self._session.get(
                robots_url,
                headers={"User-Agent": self.user_agent},
                timeout=self.request_timeout,
                allow_redirects=True,
            )
        except requests.RequestException:
            # We could not verify the rules, so do not crawl the host.
            parser.disallow_all = True
            return parser

        status = response.status_code
        if 200 <= status < 300:
            parser.parse(response.text.splitlines())
        elif 400 <= status < 500 and status not in (401, 403):
            # robots.txt is unavailable (e.g. 404); standard convention allows.
            parser.allow_all = True
        else:
            # 401/403, 5xx, unexpected status or network failure: fail closed.
            parser.disallow_all = True

        return parser

    def get_robot_parser(self, url: str) -> urllib.robotparser.RobotFileParser:
        """Retrieves or loads the cached RobotFileParser for a domain."""
        domain = self._get_domain(url)
        if domain not in self._parsers:
            self._parsers[domain] = self._load_robot_parser(url)
        return self._parsers[domain]

    def can_fetch(self, url: str) -> bool:
        """Checks if the user-agent is permitted by robots.txt to crawl the URL."""
        try:
            parser = self.get_robot_parser(url)
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            # Fail closed: an unexpected parser error must not cause a fetch.
            return False

    def get_crawl_delay(self, url: str) -> float:
        """Returns the domain's crawl delay from robots.txt, or the default delay."""
        try:
            parser = self.get_robot_parser(url)
            delay = parser.crawl_delay(self.user_agent)
            if delay is not None and delay > 0:
                return float(delay)
        except Exception:
            pass
        return self.default_delay

    def enforce_delay(self, url: str) -> float:
        """
        Calculates and pauses execution if needed to respect the domain's crawl delay.
        Returns the actual time slept in seconds.
        """
        domain = self._get_domain(url)
        delay = self.get_crawl_delay(url)
        now = time.time()

        slept = 0.0
        if domain in self._last_request_times:
            elapsed = now - self._last_request_times[domain]
            if elapsed < delay:
                slept = delay - elapsed
                time.sleep(slept)

        self._last_request_times[domain] = time.time()
        return slept
