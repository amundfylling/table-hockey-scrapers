"""Player id mapping shared by all sources, so one person gets the same id everywhere.

1. Known ITHF id that matches a Sportscorpion ``RankingID`` -> that ``PlayerID``.
2. Known ITHF id that Sportscorpion lacks, but Sportscorpion has the same name (unique, same nation) under a
   PlayerID with an empty or different RankingID -> that ``PlayerID`` ("ithf_name_sportscorpion").
3. Any other known ITHF id -> ``9_000_000 + ithfId`` (same rule as table-hockey-eu-fetch).
4. No ITHF id, but a unique Sportscorpion name match (same nation when both sides have one) -> that
   ``PlayerID`` ("sportscorpion_name").
5. Otherwise a source-local synthetic id in the source's own range.

ITHF ids come from the source itself or, where a source asks for it, from a *unique* name match
against the ITHF ranking (``ranking.txt``). Every name decision is logged for review.

Guard: a name-based Sportscorpion id is dropped for a player when, in the same tournament, a different
player of the source has that id and the two play each other (they are two people). Sources call
``begin_tournament`` / ``played`` while building rows and rebuild them when ``apply_guard`` returns True.
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
# ITHF ids of every player who ever played a Swedish (resultat API) tournament, active or not. ranking.txt only
# lists active players, so this is the fallback name -> ITHF source for players who have stopped playing.
ITHF_ARCHIVE_URL = "https://raw.githubusercontent.com/amundfylling/bordshockey.net-scraper/main/api_player_ids.csv"
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
# Country strings in players_data.csv (free text, some in Russian or misspelt) -> ITHF code(s).
_SC_COUNTRY_CODES: dict[str, tuple[str, ...]] = {
    "russia": ("RUS",), "россия": ("RUS",), "росиия": ("RUS",), "latvia": ("LAT",), "латвия": ("LAT",),
    "norway": ("NOR",), "ukraine": ("UKR",), "kazakhstan": ("KAZ",), "казакстан": ("KAZ",), "kazakistan": ("KAZ",),
    "estonia": ("EST",), "belarus": ("BLR",), "sweden": ("SWE",), "germany": ("GER",),
    "czech republic": ("CZE",), "czechia": ("CZE",), "slovakia": ("SVK",), "finland": ("FIN",),
    "slovenia": ("SLO",), "denmark": ("DEN",), "united states of america": ("USA",),
    "republic of lithuania": ("LTU",), "lithuania": ("LTU",), "switzerland": ("SUI",), "portugal": ("POR",),
    "hungary": ("HUN",), "tajikistan": ("TJK",), "israel": ("ISR",), "canada": ("CAN",), "syria": ("SYR",),
    "china": ("CHN",), "turkmenistan": ("TKM",), "kyrgyzstan": ("KGZ",), "serbia": ("SRB",), "france": ("FRA",),
    "india": ("IND",), "pakistan": ("PAK",), "spain": ("ESP",), "uzbekistan": ("UZB",), "austria": ("AUT",),
    "azerbaijan": ("AZE",), "chile": ("CHI",), "united kingdom": ("GBR",), "australia": ("AUS",),
    "italy": ("ITA",), "poland": ("POL",), "netherlands": ("NED",), "armenia": ("ARM",), "iran": ("IRN",),
    "republic of moldova": ("MDA",), "sverige": ("SWE",),
}
_NO_COUNTRY = {"", "-", "test"}
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


# Quoted nicknames: 'Raivis "The Cobra" Miglinieks', 'Eike Rompa "Fury"', 'Jan „Honza“ Novák'.
_NICKNAME = re.compile(r'["\u201c\u201d\u201e\u00ab\u00bb][^"\u201c\u201d\u201e\u00ab\u00bb]*["\u201c\u201d\u201e\u00ab\u00bb]')
# Generation suffixes after folding ("ml." -> "ml"): Czech mladší / starší, English junior / senior.
SUFFIXES = frozenset({"ml", "st", "jr", "sr", "jun", "sen"})


def strip_nickname(name: str) -> str:
    return " ".join(_NICKNAME.sub(" ", str(name)).split())


def name_key(name: str) -> frozenset[str]:
    """Order-independent token set without quoted nicknames, so "Plešák Pavel" == "Pavel Plesak" and
    'Raivis "The Cobra" Miglinieks' == "Raivis Miglinieks"."""
    return frozenset(fold(strip_nickname(name)).split())


def base_key(name_or_key) -> frozenset[str]:
    """``name_key`` without generation suffixes: "Michael Moravec ml." -> {michael, moravec}."""
    key = name_or_key if isinstance(name_or_key, frozenset) else name_key(name_or_key)
    return key - SUFFIXES


def ithf_nation(code: str | None) -> str | None:
    if not code:
        return None
    code = str(code).strip().upper()
    return ISO_TO_ITHF.get(code, code) or None


def sc_country_codes(country: str | None) -> frozenset[str] | None:
    """ITHF code(s) for a players_data.csv ``Country``; None when blank. "Sweden / Portugal" -> {SWE, POR}.
    A country we have no code for becomes ``{"?<name>"}``: it is a nation, but matches no source nation."""
    text = (country or "").strip().lower()
    if text in _NO_COUNTRY:
        return None
    codes: set[str] = set()
    for part in re.split(r"\s*[/,]\s*|\s+-\s+", text):
        part = part.strip()
        if part in _NO_COUNTRY:
            continue
        codes.update(_SC_COUNTRY_CODES.get(part, (f"?{part}",)))
    return frozenset(codes) or None


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
    # ithf id -> (nation, name) from ranking.txt
    ranking_by_id: dict[int, tuple[str, str]] = field(default_factory=dict)
    # name key -> list of (ithf id, nation, name) for players ranking.txt may lack (inactive), see ITHF_ARCHIVE_URL
    archive_by_name: dict[frozenset, list[tuple[int, str, str]]] = field(default_factory=dict)
    # base name key (no ml./st./Jr./Sr.) -> players_data.csv rows, for names printed without the suffix
    sc_by_base: dict[frozenset, list[tuple[int, str, str, int | None]]] = field(default_factory=dict)
    # base name key -> ITHF ids of ranking.txt / archive names that carry a ml./st./Jr./Sr. suffix
    suffixed_ithf: dict[frozenset, set[int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ranking_by_id:
            for cands in self.ranking_by_name.values():
                for ithf, nation, name in cands:
                    self.ranking_by_id.setdefault(ithf, (nation, name))
        if not self.sc_by_base:
            by_base: dict[frozenset, list] = defaultdict(list)
            for key, cands in self.sc_by_name.items():
                by_base[base_key(key)].extend(cands)
            self.sc_by_base = dict(by_base)
        if not self.suffixed_ithf:
            suff: dict[frozenset, set[int]] = defaultdict(set)
            for index in (self.ranking_by_name, self.archive_by_name):
                for key, cands in index.items():
                    if key & SUFFIXES:
                        suff[base_key(key)].update(c[0] for c in cands)
            self.suffixed_ithf = dict(suff)


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


def parse_ithf_archive(text: str) -> dict[frozenset, list[tuple[int, str, str]]]:
    """bordshockey.net-scraper's api_player_ids.csv (``SourceTournamentID, PlayerName, ITHF, SBHF, Nation, Club``):
    one entry per distinct (name key, ITHF id, nation)."""
    frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    by_name: dict[frozenset, dict] = defaultdict(dict)
    for name, ithf_raw, nation in zip(frame["PlayerName"], frame["ITHF"], frame["Nation"]):
        ithf = to_int(ithf_raw)
        key = name_key(name)
        if ithf is None or ithf <= 0 or not key:
            continue
        by_name[key].setdefault((ithf, nation.strip().upper()), name.strip())
    return {k: [(i, n, name) for (i, n), name in v.items()] for k, v in by_name.items()}


def load_reference(players_csv: str = PLAYERS_CSV_URL, ranking: str | None = RANKING_URL,
                   client=None, ithf_archive: str | None = None) -> ReferenceData:
    ithf_map, sc_by_name = parse_players_csv(_read_text(players_csv, client))
    ranking_by_name: dict = {}
    ok = False
    if ranking:
        try:
            ranking_by_name = parse_ranking(_read_text(ranking, client))
            ok = bool(ranking_by_name)
        except Exception as exc:  # noqa: BLE001 - a missing ranking only weakens name matching
            log.error("could not load ITHF ranking %s: %s; name matching against it is off", ranking, exc)
    archive: dict = {}
    if ithf_archive:
        try:
            archive = parse_ithf_archive(_read_text(ithf_archive, client))
        except Exception as exc:  # noqa: BLE001 - only weakens name matching for inactive players
            log.error("could not load ITHF archive %s: %s; inactive players keep source ids", ithf_archive, exc)
    log.info("reference: %d Sportscorpion RankingIDs, %d ranking names, %d archive names", len(ithf_map),
             len(ranking_by_name), len(archive))
    return ReferenceData(ithf_map, sc_by_name, ranking_by_name, ok, archive_by_name=archive)


# --------------------------------------------------------------------------------------------------
# Mapper
# --------------------------------------------------------------------------------------------------

NAME_MATCH_FIELDS = ["source_key", "source_name", "nation", "method", "result_id", "matched_name", "candidates"]
NAME_METHODS = ("ithf_name_sportscorpion", "sportscorpion_name")
ARCHIVE_METHOD = "ithf_archive"
STAT_METHODS = ("ithf_sportscorpion", "ithf_name_sportscorpion", "sportscorpion_name", "ithf_synthetic",
                "source_local")


@dataclass
class PlayerMapper:
    ref: ReferenceData
    source: str
    # unique players seen (by source key) -> method
    seen: dict[str, str] = field(default_factory=dict)
    name_log: dict[tuple[str, str], dict] = field(default_factory=dict)
    # (source key, Sportscorpion PlayerID) pairs refused by the "played each other" guard
    blocked: set[tuple[str, int]] = field(default_factory=set)
    _tournament: object = None
    _keys_by_pid: dict = field(default_factory=lambda: defaultdict(set))  # (tournament, pid) -> source keys
    _name_based: dict = field(default_factory=dict)  # (tournament, pid) -> source keys mapped by name
    _name_ithf: dict = field(default_factory=dict)  # source key -> ITHF id found by a name match
    _new_blocks: int = 0

    # -- name matching -----------------------------------------------------------------------
    def match_ranking(self, name: str, nation: str | None = None, prefer_nation: str | None = None,
                      source_key: str | None = None) -> int | None:
        """Unique ITHF id for ``name`` in ranking.txt. With ``nation`` the nation must match; with only
        ``prefer_nation`` a unique match in that nation wins over several matches elsewhere."""
        key = name_key(name)
        nation = ithf_nation(nation)
        result = None
        for method, index in (("ranking.txt", self.ref.ranking_by_name), (ARCHIVE_METHOD, self.ref.archive_by_name)):
            all_cands = index.get(key, [])
            cands = all_cands
            if nation:
                cands = [c for c in cands if c[1] == nation]
            elif prefer_nation and len(cands) > 1:
                pref = [c for c in cands if c[1] == ithf_nation(prefer_nation)]
                cands = pref or cands
            ids = {c[0] for c in cands}
            result = next(iter(ids)) if len(ids) == 1 else None
            if result is not None and method == ARCHIVE_METHOD and not (key & SUFFIXES):
                # "Jiri Chylik" may be the father or the son: refused when anyone with this base name and a
                # ml./st. suffix has another ITHF id
                others = self.ref.suffixed_ithf.get(key, set())
                if others - {result}:
                    cands, result = [c for c in cands] + [(o, "", "(suffix variant)") for o in others], None
            if all_cands or method == "ranking.txt":
                self._log(source_key or name, name, nation or prefer_nation, method, result,
                          cands[0][2] if result else "", cands)
            # the archive (inactive players too) is only asked when ranking.txt has nobody of this name
            if result is not None or all_cands:
                break
        if result is not None and source_key:
            self._name_ithf[str(source_key)] = result
        return result

    def sportscorpion_candidates(self, name: str, nation: str | None = None) -> list[tuple]:
        """players_data.csv rows with the same folded, order-free name whose country does not contradict
        ``nation`` (a row without a country is kept, so it still counts against uniqueness)."""
        key = name_key(name)
        cands = self.ref.sc_by_name.get(key, [])
        if not cands and not (key & SUFFIXES):
            # "Michael Moravec" vs Sportscorpion "Michael Moravec ml.": accepted only when exactly one
            # Sportscorpion player has this base name (checked by the caller's uniqueness rule)
            cands = self.ref.sc_by_base.get(key, [])
            # ...and refused when ranking.txt / the archive know another suffixed person of this base name
            # ("Zdeněk Matoušek st." 70029 next to Sportscorpion's "Zdeněk Matoušek ml." 70057)
            if self.ref.suffixed_ithf.get(key, set()) - {c[3] for c in cands}:
                cands = []
        nation = ithf_nation(nation)
        if not nation:
            return list(cands)
        return [c for c in cands if (codes := sc_country_codes(c[1])) is None or nation in codes]

    def match_sportscorpion(self, name: str, country_code: str | None = None,
                            source_key: str | None = None, method: str = "players_data.csv",
                            ithf: int | None = None) -> int | None:
        """Unique Sportscorpion PlayerID for this name (folded, any word order). When ``country_code`` is given
        the country must match wherever players_data.csv has one; otherwise the name must be unique overall.
        With ``ithf`` (an ITHF id Sportscorpion does not know), a candidate whose RankingID is a ranking.txt
        player with another name is not used."""
        key = source_key or name
        cands = self.sportscorpion_candidates(name, country_code)
        if ithf is not None:
            cands = [c for c in cands if c[3] is None or c[3] == ithf
                     or name_key(self.ref.ranking_by_id.get(c[3], ("", name))[1]) == name_key(name)]
        ids = {c[0] for c in cands}
        result = next(iter(ids)) if len(ids) == 1 else None
        matched = cands[0][2] if result else ""
        if result is not None and (key, result) in self.blocked:
            matched, result = f"{matched} (refused: played each other)", None
            cands = []
        self._log(key, name, country_code, method, result, matched, [(c[0], c[1], c[2]) for c in cands],
                  force=True)
        return result

    def _log(self, key, name, nation, method, result, matched, cands, force: bool = False) -> None:
        entry = self.name_log.get((key, method))
        # keep the first decisive match per key and method; overwrite non-matches with later matches
        if entry and entry["result_id"] and not result and not force:
            return
        self.name_log[(key, method)] = {
            "source_key": key, "source_name": name, "nation": nation or "", "method": method,
            "result_id": "" if result is None else str(result), "matched_name": matched,
            "candidates": "|".join(f"{c[0]}:{c[2]}:{c[1]}" for c in cands[:5]) if len(cands) != 1 or not result else "",
        }

    # -- id resolution -----------------------------------------------------------------------
    def from_ithf(self, ithf: int, name: str | None = None, nation: str | None = None,
                  source_key: str | None = None) -> tuple[int, str]:
        if ithf in self.ref.ithf_to_player:
            return self.ref.ithf_to_player[ithf], "ithf_sportscorpion"
        if name:
            ranking = self.ref.ranking_by_id.get(ithf)
            nat = ithf_nation(nation) or (ranking[0] if ranking and ranking[0] else None)
            pid = self.match_sportscorpion(name, nat, source_key or f"ithf:{ithf}",
                                           method="ithf_name_sportscorpion", ithf=ithf)
            if pid is None and ranking and name_key(ranking[1]) != name_key(name):
                pid = self.match_sportscorpion(ranking[1], nat, source_key or f"ithf:{ithf}",
                                               method="ithf_name_sportscorpion", ithf=ithf)
            if pid is not None:
                return pid, "ithf_name_sportscorpion"
        return ITHF_OFFSET + ithf, "ithf_synthetic"

    def resolve(self, source_key: str, *, ithf=None, local_id: int, sc_player_id: int | None = None,
                name: str | None = None, nation: str | None = None) -> int:
        """Final id for one player. ``sc_player_id`` is a direct Sportscorpion name match (no ITHF id); ``name``
        and ``nation`` let a known ITHF id that Sportscorpion lacks fall back to a Sportscorpion name match."""
        key = str(source_key)
        ithf = to_int(ithf)
        by_name = ithf is not None and self._name_ithf.get(key) == ithf
        if ithf is not None:
            pid, method = self.from_ithf(ithf, name, nation, key)
            if by_name and (key, pid) in self.blocked:
                ithf = None  # an ITHF id found by name, refused by the guard: fall through
        if ithf is not None:
            pass
        elif sc_player_id is not None and (key, sc_player_id) not in self.blocked:
            pid, method = sc_player_id, "sportscorpion_name"
        else:
            pid, method = local_id, "source_local"
        self.seen[key] = method
        if self._tournament is not None:
            self._keys_by_pid[(self._tournament, pid)].add(key)
            if method in NAME_METHODS or by_name:
                self._name_based.setdefault((self._tournament, pid), set()).add(key)
        return pid

    # -- "played each other" guard -------------------------------------------------------------
    def begin_tournament(self, tournament) -> None:
        """Ids resolved from now on belong to ``tournament`` (until the next call)."""
        self._tournament = tournament

    def played(self, pid1: int, pid2: int) -> None:
        """Record one game. Two different source players with the same id who play each other are two people:
        every name-based mapping to that id in this tournament is refused (applied by ``apply_guard``)."""
        if pid1 != pid2 or self._tournament is None:
            return
        slot = (self._tournament, pid1)
        if len(self._keys_by_pid.get(slot, ())) < 2:
            return
        for key in sorted(self._name_based.get(slot, ())):
            if (key, pid1) not in self.blocked:
                self.blocked.add((key, pid1))
                self._new_blocks += 1
                others = sorted(self._keys_by_pid[slot] - {key})
                log.info("%s: %s not mapped to Sportscorpion %d: plays %s in %s", self.source, key, pid1,
                         ", ".join(others), self._tournament)
                self.name_log[(key, "rejected_played_each_other")] = {
                    "source_key": key, "source_name": self._name_of(key), "nation": "",
                    "method": "rejected_played_each_other", "result_id": "", "matched_name": str(pid1),
                    "candidates": f"plays {'|'.join(others)} in tournament {self._tournament}",
                }

    def _name_of(self, key: str) -> str:
        return next((e["source_name"] for (k, _), e in self.name_log.items() if k == key), "")

    def apply_guard(self) -> bool:
        """True when ``played`` refused new mappings since the last call: the caller rebuilds its rows (the
        refused players then fall back to their ITHF synthetic or source-local id)."""
        new, self._new_blocks = self._new_blocks, 0
        self._tournament = None
        self._keys_by_pid = defaultdict(set)
        self._name_based = {}
        if new:
            self.seen = {}
        return bool(new)

    def stats(self) -> dict[str, int]:
        counts = Counter(self.seen.values())
        out = {m: counts.get(m, 0) for m in STAT_METHODS}
        out["total"] = len(self.seen)
        return out

    def write_name_matches(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = sorted(self.name_log.values(), key=lambda r: (r["source_name"], r["source_key"], r["method"]))
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, NAME_MATCH_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
