"""Fetching for stiga.trefik.cz: every response is cached under data/trefik/raw/ (gzip), keyed by URL path."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from ..common.http import AccessDenied, PoliteClient
from .discover import BASE, INDEX_URL, NEWS_URL, Listed, decode, parse_categories, parse_index, parse_news

log = logging.getLogger(__name__)


class Fetcher:
    def __init__(self, client: PoliteClient, raw_dir: Path, offline: bool = False, refresh_keys=()):
        self.client = client
        self.raw_dir = raw_dir
        self.offline = offline
        self.refresh_keys = set(refresh_keys)  # tournament keys whose pages are re-fetched (in-progress seasons)
        self.fetched = 0

    def cache_path(self, url: str) -> Path:
        parts = urlsplit(url)
        if "/cz_turnaje/" in parts.path:
            rel = parts.path.split("/cz_turnaje/", 1)[1]
        else:
            rel = parts.netloc + parts.path
        if rel.endswith("/") or not rel:
            rel += "_dir"
        if parts.query:
            rel += "_" + re.sub(r"[^A-Za-z0-9]+", "_", parts.query)
        return self.raw_dir / (rel + ".gz")

    def get(self, url: str, refresh: bool = False) -> bytes | None:
        path = self.cache_path(url)
        if not path.exists() and not self.offline:
            self.fetched += 1
        return self.client.get_bytes(url, path, refresh=refresh and not self.offline, offline=self.offline)

    def text(self, url: str, refresh: bool = False) -> str | None:
        data = self.get(url, refresh)
        return None if data is None else decode(data)


def list_tournaments(fetcher: Fetcher, refresh_index: bool = True) -> list[Listed]:
    html = fetcher.text(INDEX_URL, refresh=refresh_index)
    if html is None:
        raise RuntimeError("tournament index not available")
    listed = parse_index(html)
    news = fetcher.text(NEWS_URL, refresh=refresh_index)
    if news:
        extra = parse_news(news, {i.key for i in listed})
        if extra:
            log.info("front page links %d events the season index lacks: %s", len(extra),
                     ", ".join(i.key for i in extra))
        listed += extra
    out: list[Listed] = []
    for item in listed:
        if item.url.endswith("kategorie.aspx"):
            page = fetcher.text(item.url)
            if page is None:
                log.warning("%s: categories page missing", item.key)
                continue
            out.extend(parse_categories(page, item.url, item))
        else:
            out.append(item)
    # de-duplicate keys (a category page may link to an event also listed directly)
    seen, unique = set(), []
    for item in out:
        if item.key not in seen:
            seen.add(item.key)
            unique.append(item)
    return unique


def start_page(fetcher: Fetcher, item: Listed, refresh: bool = False) -> tuple[str, str] | None:
    """(url, html) of the tournament's main page; tries index.aspx / index.htm / the directory."""
    candidates = [] if item.url.endswith("/") else [item.url]
    base = urljoin(BASE, item.key + "/")
    for name in ("index.aspx", "index.htm", ""):
        url = base + name
        if url not in candidates:
            candidates.append(url)
    for url in candidates:
        try:
            html = fetcher.text(url, refresh=refresh)
        except AccessDenied:  # a directory without a default page
            continue
        if html and "The resource cannot be found" not in html and "404 - File or directory" not in html:
            return url, html
    return None
