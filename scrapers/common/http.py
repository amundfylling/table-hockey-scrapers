"""Polite HTTP client: one request per second per host, retries with backoff, robots.txt, raw cache."""

from __future__ import annotations

import gzip
import logging
import re
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

USER_AGENT = "table-hockey-h2h-scraper/1.0 (+https://github.com/amundfylling/table-hockey-scrapers)"
RETRY_STATUS = {429, 500, 502, 503, 504}


class AccessDenied(RuntimeError):
    """The site refused access (401/403, or an API that needs a key). Never worked around."""


class RobotsDisallowed(RuntimeError):
    """robots.txt disallows the URL."""


class PoliteClient:
    def __init__(
        self,
        min_interval: float = 1.0,
        timeout: float = 30.0,
        retries: int = 4,
        backoff: float = 2.0,
        user_agent: str = USER_AGENT,
        session: requests.Session | None = None,
    ):
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.user_agent = user_agent
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.requests_made = 0

    # -- robots ------------------------------------------------------------------------------
    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        parser = None
        try:
            resp = self._raw_get(origin + "/robots.txt", check_robots=False)
            ctype = resp.headers.get("Content-Type", "")
            # Some apps answer /robots.txt with their HTML 404 page: treat that as "no rules".
            if resp.status_code == 200 and "html" not in ctype.lower():
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(resp.text.splitlines())
                delay = parser.crawl_delay(self.user_agent)
                if delay:
                    self.min_interval = max(self.min_interval, float(delay))
        except requests.RequestException as exc:  # robots unreachable: be conservative but continue
            log.warning("robots.txt for %s not readable: %s", origin, exc)
        self._robots[origin] = parser
        return parser

    def allowed(self, url: str) -> bool:
        parser = self._robots_for(url)
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    # -- fetching ----------------------------------------------------------------------------
    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            delta = time.monotonic() - last
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
        self._last[host] = time.monotonic()

    def _raw_get(self, url: str, check_robots: bool = True, **kwargs) -> requests.Response:
        if check_robots and not self.allowed(url):
            raise RobotsDisallowed(url)
        host = urlsplit(url).netloc
        for attempt in range(self.retries + 1):
            self._wait(host)
            try:
                self.requests_made += 1
                resp = self.session.get(url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                if attempt == self.retries:
                    raise
                log.warning("GET %s failed (%s), retrying", url, exc)
            else:
                if resp.status_code not in RETRY_STATUS or attempt == self.retries:
                    return resp
                log.warning("GET %s -> %s, retrying", url, resp.status_code)
            time.sleep(self.backoff * (2**attempt))
        raise AssertionError("unreachable")

    def get(self, url: str, **kwargs) -> requests.Response:
        resp = self._raw_get(url, **kwargs)
        if resp.status_code in (401, 403):
            raise AccessDenied(f"{url} -> {resp.status_code}")
        return resp

    def get_bytes(self, url: str, cache_path: Path | None = None, refresh: bool = False,
                  offline: bool = False) -> bytes | None:
        """Fetch a URL, caching the body at ``cache_path`` (gzip-compressed if it ends in ``.gz``).

        Returns None on 404 (a 404 is cached as an empty file so it is not re-fetched), or when ``offline`` and
        nothing is cached.
        """
        if cache_path is not None and cache_path.exists() and not refresh:
            data = cache_path.read_bytes()
            if not data:
                return None
            return gzip.decompress(data) if cache_path.suffix == ".gz" else data
        if offline:
            return None
        resp = self.get(url)
        if resp.status_code == 404:
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(b"")
            return None
        resp.raise_for_status()
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            body = gzip.compress(resp.content, mtime=0) if cache_path.suffix == ".gz" else resp.content
            cache_path.write_bytes(body)
        return resp.content


_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([A-Za-z0-9_\-]+)""", re.I)


def decode_html(data: bytes, fallbacks: tuple[str, ...] = ("utf-8", "windows-1250", "windows-1257")) -> str:
    """Decode an HTML page: declared <meta charset> first, then strict UTF-8, then the fallbacks."""
    m = _META_CHARSET.search(data[:4096])
    candidates: list[str] = []
    if m:
        candidates.append(m.group(1).decode("ascii").lower())
    candidates += [c for c in fallbacks if c not in candidates]
    for enc in candidates:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode(fallbacks[-1], errors="replace")
