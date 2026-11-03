"""Trefik parser/transform tests on real pages saved from stiga.trefik.cz (tests/trefik/fixtures/raw)."""

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from scrapers.common import trefik_sw as sw
from scrapers.common.http import PoliteClient
from scrapers.common.players import load_reference
from scrapers.common.report import SkipCounter
from scrapers.trefik import IdResolver, PlayerMapper, parse_html_event, parse_json_event, resolve_groups
from scrapers.trefik.crawl import Fetcher, list_tournaments
from scrapers.trefik.discover import Listed

FIX = Path(__file__).parent / "fixtures" / "raw"
COMMON = Path(__file__).parents[1] / "common" / "fixtures"


@pytest.fixture(scope="module")
def fetcher():
    return Fetcher(PoliteClient(), FIX, offline=True)


@pytest.fixture(scope="module")
def listed(fetcher):
    return {item.key: item for item in list_tournaments(fetcher, refresh_index=False)}


def _event(fetcher, listed, key):
    skips = SkipCounter()
    item = listed[key]
    parsed = (parse_json_event(fetcher, item, skips, False) if item.kind == "json"
              else parse_html_event(fetcher, item, skips, False))
    parsed = parsed if isinstance(parsed, list) else [parsed]
    pool = {int(p.date[:4]): list(p.players) for p in parsed}
    for p in parsed:
        resolve_groups(p, pool, skips)
    return parsed, skips


def test_index_lists_every_season(listed):
    seasons = Counter(item.season for item in listed.values())
    assert len(listed) >= 300
    assert seasons[2025] == 17 and seasons[2010] == 11
    assert listed["turnaje2025/cheb"].index_date == "23.11.2024"
    assert listed["turnaje2026/co"].kind == "json"
    assert listed["turnaje2025/mrvet"].category == "Veterans"
    assert listed["turnaje2025/mrdr"].is_team_event
    assert not any(k.split("/")[1] in ("data", "data_new") for k in listed if "/" in k)


@pytest.mark.parametrize("text,expected", [
    ("Cheb, 23. listopad 2024", date(2024, 11, 23)),
    ("MR jednotlivů, Jihlava, 1. června 2014", date(2014, 6, 1)),
    ("Czech Open, 22. duben 2023", date(2023, 4, 22)),
    ("12. - 13.6.2004", date(2004, 6, 12)),
    ("28.-29.5.2022", date(2022, 5, 28)),
    ("Inčukalns THC Challenge, 27. September 2025", date(2025, 9, 27)),
])
def test_dates(text, expected):
    assert sw.parse_date_text(text) == expected


def test_abbreviations():
    assert sw.abbrev_matches("Kr Lebl", "Lebl Kryštof")
    assert sw.abbrev_matches("L.Turoň", "Turoň Lukáš")
    assert sw.abbrev_matches("Zd Matoušek ml.", "Matoušek ml. Zdeněk")
    assert not sw.abbrev_matches("Zd Matoušek ml.", "Matoušek st. Zdeněk")
    assert sw.abbrev_matches("ml Chylík", "Chylík ml. Jiří") and sw.abbrev_matches("m.Chylík", "Chylík ml. Jiří")
    assert sw.abbrev_matches("Vojta Kraus", "Kraus Vojtěch")
    assert not sw.abbrev_matches("Vo Kraus", "Kraus Vladimír")
    assert sw.display_name("Matoušek ml. Zdeněk") == "Zdeněk Matoušek ml."
    assert sw.display_name("Plešák, Pavel") == "Pavel Plešák"
    assert sw.clean_name("- Kalninš Rainers (A1/1)") == "Kalninš Rainers"


def test_modern_event_matches_player_overview(fetcher, listed):
    """Němčice 2023: every game of Patrik Petr equals his overview page (thstats/overview_b.aspx?idpl=409)."""
    (p,), skips = _event(fetcher, listed, "turnaje2024/nemcice")
    assert p.date == "2023-11-11" and p.name == "Czech Cup Němčice 2023"
    mine = [g for g in p.games if "Petr Patrik" in (g.p1, g.p2)]
    assert len(mine) == 38
    as_seen = Counter((g.stage, g.p2 if g.p1 == "Petr Patrik" else g.p1,
                       (g.g1, g.g2) if g.p1 == "Petr Patrik" else (g.g2, g.g1)) for g in mine)
    assert as_seen[("Basic groups 2", "Lebl Kryštof", (6, 5))] == 1
    assert as_seen[("Basic groups 2", "Ženíšek Martin", (6, 6))] == 1  # draws are kept
    assert as_seen[("Final groups A", "Kobrle Michal", (1, 1))] == 1
    assert [k for k in as_seen if k[0] == "Playoff Final"] == [
        ("Playoff Final", "Kobrle Michal", (11, 2)), ("Playoff Final", "Kobrle Michal", (10, 3)),
        ("Playoff Final", "Kobrle Michal", (7, 4))]
    rnd = {g.p2 if g.p1 == "Petr Patrik" else g.p1: g.round for g in mine if g.stage == "Basic groups 2"}
    assert rnd["Martinec Martin"] == 1 and rnd["Bucek Tomáš"] == 21
    # carried-over results in final groups and walkovers ("5:0 K") in the play-off are not games
    assert skips.counts["result carried forward / forfeit (K)"] > 0
    assert skips.counts["play-off walkover (K)"] >= 2
    assert len({g.match_id for g in p.games}) == len(p.games)


def test_old_htm_event_resolves_initials(fetcher, listed):
    (p,), skips = _event(fetcher, listed, "turnaje2010/cheb")
    assert p.date == "2010-03-13"
    assert not skips.counts["cross-table name not resolved"]
    final = [g for g in p.games if g.stage == "Playoff Final"]
    assert [(g.g1, g.g2, g.overtime) for g in final][:2] == [(3, 2, True), (2, 4, False)]
    assert final[0].p1 == "Turoň Lukáš" and final[0].p2 == "Matoušek ml. Zdeněk"
    double = [g for g in p.games if g.stage == "Final groups C"]
    assert len(double) == 42  # 7 players, double round robin
    assert skips.counts["result carried forward / forfeit (K)"] == 84


def test_czech_open_ids_and_overview(fetcher, listed):
    (p,), _ = _event(fetcher, listed, "turnaje2023/co2023")
    ref = p.players["Kalninš Rainers"]
    assert ref.idpl == 1761 and ref.ithf == 655257
    kal = [g for g in p.games if "Kalninš Rainers" in (g.p1, g.p2)]
    assert len(kal) == 58  # = thstats/overview_b.aspx?idpl=1761&x=-390
    assert len({(g.p1, g.p2, g.stage) for g in p.games if g.stage.startswith("Final groups")}) > 0


def test_json_event(fetcher, listed):
    (p,), skips = _event(fetcher, listed, "turnaje2026/trinec_new")
    assert p.date == "2026-03-21" and p.name == "Czech Cup Třinec 2026"
    assert p.players["Plešák, Pavel"].idpl == 1 and p.players["Plešák, Pavel"].ithf == 70001
    po = [g for g in p.games if g.stage_type == "playoff"]
    assert po and all(g.game_no for g in po)
    assert len({g.match_id for g in p.games}) == len(p.games)


def test_championship_hub_is_split_by_category(fetcher, listed):
    item = Listed("turnaje2011/mr", "https://stiga.trefik.cz/cz_turnaje/turnaje2011/mr/index.htm", 2011,
                  "MR, Litomyšl", "MR, Litomyšl", "29.5.2011", "")
    skips = SkipCounter()
    parsed = parse_html_event(fetcher, item, skips, False)
    names = sorted(p.name for p in parsed)
    assert "Czech Championship 2011" in names and "Czech Championship 2011 – Women" in names
    assert skips.counts["team championship (not individual games)"] >= 0


def test_player_ids(fetcher, listed):
    ref = load_reference(str(COMMON / "players_data_sample.csv"), str(COMMON / "ranking_sample.txt"))
    (p,), _ = _event(fetcher, listed, "turnaje2023/co2023")
    from scrapers.common.registry import IdRegistry

    mapper = PlayerMapper(ref, "trefik")
    resolver = IdResolver([p], mapper, IdRegistry(Path("/nonexistent/x.csv"), 21_000_001))
    assert resolver.resolve(p.players["Kalninš Rainers"]) == 9_000_000 + 655257   # ITHF via the list page
    assert resolver.resolve(p.players["Plešák Pavel"]) == 9_000_000 + 70001       # ranking.txt name match (CZE)
    assert resolver.resolve(p.players["Petr Patrik"]) == 9_000_000 + 70409       # ITHF id from the list page
    from scrapers.trefik import PlayerRef

    assert resolver.resolve(PlayerRef("Neznámý Hráč", idpl=99999)) == 20_000_000 + 99999  # idpl, no ITHF id
    assert resolver.resolve(PlayerRef("Neznámý Druhý")) == 21_000_001                    # nothing: registry
