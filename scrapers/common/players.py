"""Player id mapping shared by all sources, so one person gets the same id everywhere.

1. Known ITHF id that matches a Sportscorpion ``RankingID`` -> that ``PlayerID``.
2. Any other known ITHF id -> ``9_000_000 + ithfId`` (same rule as table-hockey-eu-fetch).
3. Otherwise a source-local synthetic id in the source's own range.

ITHF ids come from the source itself or, where a source asks for it, from a *unique* name match
against the ITHF ranking (``ranking.txt``). Some sources may also fall back to a unique exact name match
against Sportscorpion's ``players_data.csv``. Every name decision is logged for review.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

PLAYERS_CSV_URL = "https://raw.githubusercontent.com/amundfylling/Scorpion-Scraper-2.0/main/data/players_data.csv"
RANKING_URL = "https://stiga.trefik.cz/ithf/ranking/ranking.txt"
ITHF_OFFSET = 9_000_000

# ITHF/IOC-style codes used by ranking.txt and the sources, mapped to Sportscorpion country names.
COUNTRY_NAMES: dict[str, str] = {
    "LAT": "Latvia", "LVA": "Latvia", "CZE": "Czech Republic", "FIN": "Finland", "SWE": "Sweden",
    "NOR": "Norway", "EST": "Estonia", "RUS": "Russia", "UKR": "Ukraine", "BLR": "Belarus",
    "KAZ": "Kazakhstan", "GER": "Germany", "DEU": "Germany", "SVK": "Slovakia", "SLO": "Slovenia",
    "SVN": "Slovenia", "DEN": "Denmark", "DNK": "Denmark", "LTU": "Republic of Lithuania", "SUI": "Switzerland",
    "CHE": "Switzerland", "HUN": "Hungary", "AUT": "Austria", "USA": "United States of America",
    "CAN": "Canada", "POR": "Portugal", "PRT": "Portugal", "POL": "Poland", "FRA": "France",
}
# ISO alpha-3 codes that differ from the ITHF code used in ranking.txt.
ISO_TO_ITHF = {"LVA": "LAT", "DEU": "GER", "SVN": "SLO", "DNK": "DEN", "CHE": "SUI", "PRT": "POR"}

_EXTRA_FOLD = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ß": "ss", "æ": "ae",
                             "Æ": "AE", "ı": "i"})


def to_int(value) -> int | None:
    """Parse ids stored as 668143, "668143", 668143.0 or "668143.0"; None for blanks."""
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float):
        return None if pd.isna(value) else int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def fold(text: str) -> str:
    """ASCII-fold, lowercase and collapse whitespace: "Plešák  Pavel" -> "plesak pavel"."""
    text = unicodedata.normalize("NFKD", str(text).translate(_EXTRA_FOLD))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return " ".join(text.split())


def name_key(name: str) -> frozenset[str]:
    """Order-independent token set, so "Plešák Pavel" == "Pavel Plesak"."""
    return frozenset(fold(name).split())


def ithf_nation(code: str | None) -> str | None:
    if not code:
        return None
    code = str(code).strip().upper()
    return ISO_TO_ITHF.get(code, code) or None


# --------------------------------------------------------------------------------------------------
# Reference data (loaded once per run, shared by all sources)
# --------------------------------------------------------------------------------------------------


@dataclass
class ReferenceData:
    ithf_to_player: dict[int, int]
    # name key -> list of (PlayerID, Country, Name, RankingID) from players_data.csv
    sc_by_name: dict[frozenset, list[tuple[int, str, str, int | None]]]
    # name key -> list of (ithf id, nation, name) from ranking.txt
    ranking_by_name: dict[frozenset, list[tuple[int, str, str]]]
    ranking_available: bool = True


def _read_text(source: str, client=None) -> str:
    if source.startswith(("http://", "https://")):
        if client is None:
            from .http import PoliteClient

            client = PoliteClient()
        resp = client.get(source)
        resp.raise_for_status()
        return resp.content.decode("utf-8-sig", errors="replace")
    return Path(source).read_text(encoding="utf-8-sig", errors="replace")


def parse_players_csv(text: str) -> tuple[dict[int, int], dict[frozenset, list]]:
    frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    ithf_map: dict[int, int] = {}
    by_name: dict[frozenset, list] = defaultdict(list)
    duplicates = 0
    for pid_raw, name, rid_raw, country in zip(frame["PlayerID"], frame["Name"], frame["RankingID"], frame["Country"]):
        pid, rid = to_int(pid_raw), to_int(rid_raw)
        if pid is None:
            continue
        if rid is not None:
            if rid in ithf_map:
                duplicates += 1
                pid_for_rid = min(pid, ithf_map[rid])  # deterministic, same rule as table-hockey-eu-fetch
            else:
                pid_for_rid = pid
            ithf_map[rid] = pid_for_rid
        key = name_key(name)
        if key:
            by_name[key].append((pid, country.strip(), name, rid))
    if duplicates:
        log.warning("%d RankingIDs appear more than once in players_data.csv", duplicates)
    return ithf_map, dict(by_name)


def parse_ranking(text: str) -> dict[frozenset, list[tuple[int, str, str]]]:
    """ranking.txt: tab separated ``Rank, ID_Player, Player, Club, Nation, Points, Player_Value``."""
    by_name: dict[frozenset, list] = defaultdict(list)
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    for row in reader:
        if len(row) < 5 or not row[1].strip().isdigit():
            continue  # header or junk
        ithf, name, nation = int(row[1]), row[2].strip(), row[4].strip().upper()
        by_name[name_key(name)].append((ithf, nation, name))
    return dict(by_name)


def load_reference(players_csv: str = PLAYERS_CSV_URL, ranking: str | None = RANKING_URL,
                   client=None) -> ReferenceData:
    ithf_map, sc_by_name = parse_players_csv(_read_text(players_csv, client))
    ranking_by_name: dict = {}
    ok = False
    if ranking:
        try:
            ranking_by_name = parse_ranking(_read_text(ranking, client))
            ok = bool(ranking_by_name)
        except Exception as exc:  # noqa: BLE001 - a missing ranking only weakens name matching
            log.error("could not load ITHF ranking %s: %s; name matching against it is off", ranking, exc)
    log.info("reference: %d Sportscorpion RankingIDs, %d ranking names", len(ithf_map), len(ranking_by_name))
    return ReferenceData(ithf_map, sc_by_name, ranking_by_name, ok)


# --------------------------------------------------------------------------------------------------
# Mapper
# --------------------------------------------------------------------------------------------------

NAME_MATCH_FIELDS = ["source_key", "source_name", "nation", "method", "result_id", "matched_name", "candidates"]


@dataclass
class PlayerMapper:
    ref: ReferenceData
    source: str
    # unique players seen (by source key) -> method
    seen: dict[str, str] = field(default_factory=dict)
    name_log: dict[str, dict] = field(default_factory=dict)

    # -- name matching -----------------------------------------------------------------------
    def match_ranking(self, name: str, nation: str | None = None, prefer_nation: str | None = None,
                      source_key: str | None = None) -> int | None:
        """Unique ITHF id for ``name`` in ranking.txt. With ``nation`` the nation must match; with only
        ``prefer_nation`` a unique match in that nation wins over several matches elsewhere."""
        key = name_key(name)
        cands = self.ref.ranking_by_name.get(key, [])
        nation = ithf_nation(nation)
        if nation:
            cands = [c for c in cands if c[1] == nation]
        elif prefer_nation and len(cands) > 1:
            pref = [c for c in cands if c[1] == ithf_nation(prefer_nation)]
            cands = pref or cands
        ids = {c[0] for c in cands}
        result = next(iter(ids)) if len(ids) == 1 else None
        self._log(source_key or name, name, nation or prefer_nation, "ranking.txt", result,
                  cands[0][2] if result else "", cands)
        return result

    def match_sportscorpion(self, name: str, country_code: str | None = None,
                            source_key: str | None = None) -> int | None:
        """Unique Sportscorpion PlayerID with exactly this folded name (and country, if given)."""
        cands = self.ref.sc_by_name.get(name_key(name), [])
        country = COUNTRY_NAMES.get(ithf_nation(country_code) or "", None) if country_code else None
        if country:
            cands = [c for c in cands if c[1] == country]
        ids = {c[0] for c in cands}
        result = next(iter(ids)) if len(ids) == 1 else None
        self._log(source_key or name, name, country_code, "players_data.csv", result,
                  cands[0][2] if result else "", [(c[0], c[1], c[2]) for c in cands])
        return result

    def _log(self, key, name, nation, method, result, matched, cands) -> None:
        entry = self.name_log.get(key)
        # keep the first decisive match per key; overwrite non-matches with later matches
        if entry and entry["result_id"] and not result:
            return
        self.name_log[key] = {
            "source_key": key, "source_name": name, "nation": nation or "", "method": method,
            "result_id": "" if result is None else str(result), "matched_name": matched,
            "candidates": "|".join(f"{c[0]}:{c[2]}:{c[1]}" for c in cands[:5]) if len(cands) != 1 or not result else "",
        }

    # -- id resolution -----------------------------------------------------------------------
    def from_ithf(self, ithf: int) -> tuple[int, str]:
        if ithf in self.ref.ithf_to_player:
            return self.ref.ithf_to_player[ithf], "ithf_sportscorpion"
        return ITHF_OFFSET + ithf, "ithf_synthetic"

    def resolve(self, source_key: str, *, ithf=None, local_id: int, sc_player_id: int | None = None) -> int:
        """Final id for one player. ``sc_player_id`` is a direct Sportscorpion name match (no ITHF id)."""
        ithf = to_int(ithf)
        if ithf is not None:
            pid, method = self.from_ithf(ithf)
        elif sc_player_id is not None:
            pid, method = sc_player_id, "sportscorpion_name"
        else:
            pid, method = local_id, "source_local"
        self.seen[str(source_key)] = method
        return pid

    def stats(self) -> dict[str, int]:
        counts = Counter(self.seen.values())
        out = {m: counts.get(m, 0) for m in ("ithf_sportscorpion", "ithf_synthetic", "sportscorpion_name",
                                             "source_local")}
        out["total"] = len(self.seen)
        return out

    def write_name_matches(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = sorted(self.name_log.values(), key=lambda r: (r["source_name"], r["source_key"]))
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, NAME_MATCH_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
