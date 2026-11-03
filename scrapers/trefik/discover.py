"""Tournament list for stiga.trefik.cz, from the Czech federation's season index (stolni-hokej.cz/pohar.html)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..common.http import decode_html

INDEX_URL = "https://www.stolni-hokej.cz/pohar.html"
BASE = "https://stiga.trefik.cz/cz_turnaje/"

# Season statistics, not tournaments.
_STATS_DIRS = {"data", "data_new"}
# Labels of national-championship categories on the index (2023+), and on kategorie.aspx (2018-2022).
CATEGORY_LABELS = {
    "mr": "", "jednotlivci": "", "veterani": "Veterans", "juniori": "Juniors", "zeny": "Women",
    "55+": "55+", "nad 50 let": "50+", "u13": "U13", "do 13 let": "U13", "druzstva": "Teams",
    "juniori + zeny": "Juniors + Women",
}


@dataclass
class Listed:
    """One tournament as linked from the season index."""

    key: str            # stable key = URL path under cz_turnaje without the file, e.g. "turnaje2023/co2023"
    url: str            # page to start from (index.aspx/.htm, a directory, or ranking.html?tour=..&src=..)
    season: int         # season end year (turnajeYYYY; "99" = 1999)
    label: str          # link text, e.g. "Cheb", "Czech Open, Praha", "MR", "junioři"
    row_label: str      # the whole index row's first link text (e.g. "MR, Turnov")
    index_date: str     # date text on the index, e.g. "22.11.2025" or "28.-29.5.2022"
    category: str | None = None  # national championship category ("" = open/individual), None = not an MR event
    kind: str = "html"  # "html" (Trefik SW pages) or "json" (2026 ranking.html?tour=&src=)

    @property
    def is_team_event(self) -> bool:
        return self.category == "Teams" or self.key.rstrip("/").endswith("mrdr")


def _fold(text: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


def key_for(url: str) -> str:
    """turnaje2023/co2023 for .../cz_turnaje/turnaje2023/co2023/index.aspx; for JSON events turnaje2026/co."""
    parts = urlsplit(url)
    path = parts.path.split("/cz_turnaje/", 1)[-1]
    if path.endswith("ranking.html"):
        tour = re.search(r"tour=([^&]+)", parts.query)
        return path.rsplit("/", 1)[0] + "/" + (tour.group(1) if tour else "")
    if re.search(r"\.(aspx|htm|html)$", path, re.I) or path.endswith("/vysl"):
        path = path.rsplit("/", 1)[0]
    return path.strip("/").lower()


def season_of(key: str) -> int:
    first = key.split("/", 1)[0]
    m = re.match(r"turnaje(\d{4})$", first)
    if m:
        return int(m.group(1))
    if first == "99":
        return 1999
    raise ValueError(key)


def _is_tournament_link(url: str) -> bool:
    if "/cz_turnaje/" not in url:
        return False
    path = urlsplit(url).path.split("/cz_turnaje/", 1)[1]
    first, _, rest = path.partition("/")
    if not (re.match(r"turnaje\d{4}$", first) or first == "99"):
        return False  # ted20xx etc. = season statistics
    sub = rest.split("/", 1)[0]
    return bool(sub) and sub not in _STATS_DIRS or "ranking.html" in rest


def parse_index(html: str) -> list[Listed]:
    soup = BeautifulSoup(html, "lxml")
    out: list[Listed] = []
    seen: set[str] = set()
    for tr in soup.find_all("tr"):
        kdy = tr.find("td", class_="kdy")
        links = [a for a in tr.find_all("a", href=True) if _is_tournament_link(urljoin(INDEX_URL, a["href"]))]
        if not links:
            continue
        date_text = " ".join(kdy.get_text(" ", strip=True).split()) if kdy else ""
        row_label = " ".join(links[0].get_text(" ", strip=True).split())
        multi = len(links) > 1
        for a in links:
            url = urljoin(INDEX_URL, a["href"].strip())
            key = key_for(url)
            if key in seen:
                continue
            seen.add(key)
            label = " ".join(a.get_text(" ", strip=True).split())
            category = None
            slug = key.split("/")[-1]
            if multi or re.match(r"mr\b|mr$", _fold(row_label)) or _fold(row_label).startswith(("mr,", "mr -")) \
                    or " - mr" in _fold(row_label) or slug.startswith("mr"):
                category = CATEGORY_LABELS.get(_fold(label), "" if not multi else label)
            kind = "json" if "ranking.html" in url else "html"
            out.append(Listed(key, url, season_of(key), label, row_label, date_text, category, kind))
    return out


def parse_categories(html: str, page_url: str, parent: Listed) -> list[Listed]:
    """kategorie.aspx (national championships 2018-2022) -> one Listed per category."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a", href=True):
        label = " ".join(a.get_text(" ", strip=True).split())
        cat = CATEGORY_LABELS.get(_fold(label))
        if cat is None:
            continue
        url = urljoin(page_url, a["href"].strip())
        key = key_for(url)
        out.append(Listed(key, url, parent.season, label, parent.row_label, parent.index_date, cat, "html"))
    return out


def decode(data: bytes) -> str:
    """Trefik pages often declare windows-1250 but are UTF-8; try strict UTF-8 first."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return decode_html(data, fallbacks=("windows-1250", "iso-8859-2"))
