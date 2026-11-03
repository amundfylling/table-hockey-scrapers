"""Find the Trefik SW result folders (and Google Sheets) linked from galdahokejs.lv's Joomla pages."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..common.http import PoliteClient, decode_html

log = logging.getLogger(__name__)

HOME = "https://galdahokejs.lv/"
EXTRA_START = [
    "https://galdahokejs.lv/index.php/en/rcup/rcup-hist",
    "https://galdahokejs.lv/index.php/en/ech2024",
    "https://galdahokejs.lv/index.php/turniri",
]
SECTIONS = ("lc", "lk", "rcup", "lo", "roc", "kc", "al", "skolas")
FIRST_YEAR = 2022  # the source only covers 2022-05-01 .. 2025-11-30; older season pages are not crawled
_COVERED_ELSEWHERE = ("tablehockey.me", "sportscorpion.com", "escore.live", "table-hockey.eu")


@dataclass
class Found:
    stats: dict[str, set[str]] = field(default_factory=dict)   # folder -> linked stats page URLs
    sheets: dict[str, set[str]] = field(default_factory=dict)  # Google Sheets URL -> pages linking it
    pages: list[str] = field(default_factory=list)


def _years(url: str) -> list[int]:
    return [int(y) for y in re.findall(r"(20\d\d)", url)]


def wanted_page(url: str) -> bool:
    parts = urlsplit(url)
    if parts.netloc.replace("www.", "") != "galdahokejs.lv":
        return False
    path = parts.path
    if not (path.startswith("/index.php/turniri") or path.startswith("/index.php/en/")):
        return False
    years = _years(path)
    return not years or max(years) >= FIRST_YEAR


def page_cache(raw_dir: Path, url: str) -> Path:
    path = urlsplit(url).path.strip("/").replace("index.php/", "") or "home"
    return raw_dir / "pages" / (re.sub(r"[^A-Za-z0-9/_-]+", "_", path) + ".html.gz")


def crawl_pages(client: PoliteClient, raw_dir: Path, offline: bool = False, refresh_home: bool = True) -> Found:
    """Home page menu -> every section/season page from 2022 on (one level of subpages)."""
    found = Found()
    queue = [HOME, *EXTRA_START]
    seen = set(queue)
    depth = {u: 0 for u in queue}
    while queue:
        url = queue.pop(0)
        data = client.get_bytes(url, page_cache(raw_dir, url), refresh=refresh_home and url == HOME and not offline,
                                offline=offline)
        if not data:
            continue
        found.pages.append(url)
        soup = BeautifulSoup(decode_html(data, fallbacks=("utf-8", "windows-1257", "windows-1250")), "lxml")
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"].strip()).split("#")[0]
            low = href.lower()
            if any(host in low for host in _COVERED_ELSEWHERE):
                continue
            if "docs.google.com/spreadsheets" in low:
                found.sheets.setdefault(href, set()).add(url)
                continue
            m = re.search(r"galdahokejs\.lv/stats/([^/]+)/([^/?#]+\.php)", href, re.I)
            if m:
                found.stats.setdefault(m.group(1), set()).add(href.replace("://www.", "://"))
                continue
            if href not in seen and wanted_page(href) and depth[url] < 3:
                seen.add(href)
                depth[href] = depth[url] + 1
                queue.append(href)
    return found
