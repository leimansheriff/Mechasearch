"""HTML parsing for page title, visible text, outgoing links and canonical URL."""

import re
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# Elements that are metadata or not visible page content.
NON_VISIBLE_TAGS = ("script", "style", "noscript", "template", "svg", "title")

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class ExtractedPage:
    """Parsed representation of one HTML document."""

    title: str = ""
    text: str = ""
    links: List[str] = field(default_factory=list)
    canonical_url: Optional[str] = None


def _clean_title(soup: BeautifulSoup) -> str:
    """Returns the <title>, falling back to the first <h1>, or an empty string."""
    if soup.title:
        title = soup.title.get_text(" ", strip=True)
        if title:
            return title

    heading = soup.find("h1")
    if heading:
        return heading.get_text(" ", strip=True)

    return ""


def _clean_text(soup: BeautifulSoup) -> str:
    """Collapses HTML into readable, single-spaced visible text."""
    for tag in soup.find_all(NON_VISIBLE_TAGS):
        tag.decompose()

    raw_text = soup.get_text(separator=" ")
    return _WHITESPACE_RE.sub(" ", raw_text).strip()


def _find_canonical_url(soup: BeautifulSoup, page_url: str) -> Optional[str]:
    """Resolves the document's <link rel="canonical"> target, if present."""
    for link in soup.find_all("link", href=True):
        rel = link.get("rel") or []
        if isinstance(rel, str):
            rel = [rel]
        if any(value.lower() == "canonical" for value in rel):
            resolved = urljoin(page_url, link["href"].strip())
            return resolved or None
    return None


def _extract_links(soup: BeautifulSoup, page_url: str) -> List[str]:
    """Returns unique absolute http(s) links in document order."""
    links: List[str] = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href:
            continue

        resolved = urljoin(page_url, href)
        if not resolved.lower().startswith(("http://", "https://")):
            continue

        if resolved not in seen:
            seen.add(resolved)
            links.append(resolved)

    return links


def extract_page(html: str, page_url: str) -> ExtractedPage:
    """Extract title, visible text, outgoing links and canonical URL from HTML.

    ``page_url`` is used both as the base for relative links and as the
    fallback identity of the page when no canonical URL is declared.
    """
    if not html:
        return ExtractedPage()

    soup = BeautifulSoup(html, "html.parser")

    title = _clean_title(soup)
    canonical_url = _find_canonical_url(soup, page_url)
    links = _extract_links(soup, page_url)
    text = _clean_text(soup)

    return ExtractedPage(
        title=title,
        text=text,
        links=links,
        canonical_url=canonical_url,
    )
