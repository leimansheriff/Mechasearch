"""URL safety, normalization, and domain boundary filtering."""

from urllib.parse import urlparse, urlunparse, urljoin, parse_qsl, urlencode
from typing import List, Optional

# Non-HTML static asset extensions to reject early
IGNORED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".css", ".js", ".json", ".xml",
    ".exe", ".bin", ".hex"
}

# Common tracking parameters to strip for deduplication
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "fbclid", "gclid", "_ga"
}


class URLSafety:
    """Provides methods for URL normalization, validation, and domain filtering."""

    @staticmethod
    def is_allowed_domain(url: str, allowed_domains: List[str]) -> bool:
        """
        Validates if the URL belongs to an allowlisted domain.
        Subdomains of the allowed domains are permitted (e.g. docs.arduino.cc).
        """
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower().split(":")[0]  # Strip any port
            if not netloc:
                return False
            for allowed in allowed_domains:
                allowed_clean = allowed.lower().split(":")[0]
                if netloc == allowed_clean or netloc.endswith("." + allowed_clean):
                    return True
            return False
        except Exception:
            return False

    @staticmethod
    def has_ignored_extension(url: str) -> bool:
        """Checks if URL targets non-HTML binary or asset files."""
        try:
            path = urlparse(url).path.lower()
            return any(path.endswith(ext) for ext in IGNORED_EXTENSIONS)
        except Exception:
            return True

    @staticmethod
    def normalize_url(raw_url: str, base_url: Optional[str] = None) -> Optional[str]:
        """
        Normalizes a URL by:
        1. Resolving relative links against base_url
        2. Lowercasing scheme and host
        3. Stripping URL fragments (#section)
        4. Removing tracking query parameters
        5. Sorting remaining query parameters
        6. Rejecting non-http/https schemes and excessively long URLs (>250 chars)
        """
        if not raw_url or not isinstance(raw_url, str):
            return None

        raw_url = raw_url.strip()

        # Resolve relative URL if base_url is supplied
        if base_url:
            resolved = urljoin(base_url, raw_url)
        else:
            resolved = raw_url

        try:
            parsed = urlparse(resolved)
        except Exception:
            return None

        # Accept only http and https
        if parsed.scheme.lower() not in ("http", "https"):
            return None

        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()

        # Remove default ports
        if netloc.endswith(":80") and scheme == "http":
            netloc = netloc[:-3]
        elif netloc.endswith(":443") and scheme == "https":
            netloc = netloc[:-4]

        # Spider-trap guard: max length check
        if len(resolved) > 250:
            return None

        # Clean path: normalize empty path to '/'
        path = parsed.path or "/"
        # Normalize redundant slashes
        while "//" in path:
            path = path.replace("//", "/")

        # Filter query parameters
        clean_params = []
        if parsed.query:
            for k, v in parse_qsl(parsed.query, keep_blank_values=True):
                if k.lower() not in TRACKING_PARAMS:
                    clean_params.append((k, v))
            clean_params.sort()  # Canonicalize order

        clean_query = urlencode(clean_params)

        # Reconstruct without fragment
        normalized = urlunparse((scheme, netloc, path, "", clean_query, ""))
        return normalized
