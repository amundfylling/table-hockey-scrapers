"""ITHF archive backfill (World Championship 2017) on the pages saved from the Wayback Machine."""

from collections import Counter
from pathlib import Path

from scrapers.common import trefik_sw as sw
from scrapers.common.report import SkipCounter
from scrapers.ithf_archive import EVENTS, finish_category, parse_category, surname_first

ROOT = Path(__file__).parents[2]
WC = EVENTS[0]
RAW = ROOT / "data" / "ithf_archive" / WC.key / "raw"


def _category(prefix: str, suffix: str = ""):
    skips = SkipCounter()
    parsed = [p for c, s in WC.categories if (p := parse_category(RAW, WC, c, s, skips))]
    names = sorted({n for p in parsed for n in p.players})
    p = next(p for p in parsed if p.key.endswith("/" + prefix))
    finish_category(p, names, skips)
    return p, skips


def test_nation_column_is_not_a_score_cell():
    html = ('<table><tr><td class=kt>Ma Borisov</td><td class=ic>RUS</td><td class=kx>*</td><td>4:2</td></tr>'
            '<tr><td class=kt>Ha Österman</td><td class=ic>SWE</td><td>2:4</td><td class=kx>*</td></tr></table>')
    g = sw.parse_groups_page(html)[0]
    assert [(r.label, r.nation, r.cells) for r in g.rows] == [
        ("Ma Borisov", "RUS", ["*", "4:2"]), ("Ha Österman", "SWE", ["2:4", "*"])]


def test_empty_nation_cell_in_a_nation_column_is_skipped_too():
    # Czech championships 2019+: players without a nation get an empty nation cell
    html = ('<table><tr><td class=kt>Zd Matoušek ml.</td><td class=ic>CZE</td><td class=kx>*</td><td>4:2</td></tr>'
            '<tr><td class=kt>Be Hána</td><td class=ic>&nbsp;</td><td>2:4</td><td class=kx>*</td></tr></table>')
    g = sw.parse_groups_page(html)[0]
    assert [(r.nation, r.cells) for r in g.rows] == [("CZE", ["*", "4:2"]), (None, ["2:4", "*"])]


def test_label_prefix_keeps_accents_and_leading_generation_mark():
    g = sw.Group("basic", "1", [sw.CrossRow("Ma Papp", []), sw.CrossRow("Má Papp", []),
                                sw.CrossRow("ml Chylík", [])])
    sw.resolve_group_names(g, ["Magor Papp", "Mátyás Papp", "ml. Jiří Chylík", "Jiří Chylík"])
    assert [r.full for r in g.rows] == ["Magor Papp", "Mátyás Papp", "ml. Jiří Chylík"]


def test_surname_first():
    assert surname_first("Maxim Borisov") == "Borisov, Maxim"
    assert surname_first("ml. Jiří Chylík") == "Chylík ml., Jiří"
    assert surname_first("I Martin Vépy") == "Vépy I, Martin"
    assert sw.display_name(surname_first("ml. Jiří Chylík")) == "Jiří Chylík ml."


def test_open_games_and_players():
    p, skips = _category("open")
    stages = Counter(g.stage for g in p.games)
    # 4 basic groups of 19 and 4 of 18, every game played
    assert [stages[f"Basic groups {i}"] for i in range(1, 9)] == [171] * 4 + [153] * 4
    # final group A1: 32 players, 136 cells carried over from the basic groups or forfeited by Jevgeni Lvov
    assert stages["Final groups A1"] == 360
    game = next(g for g in p.games if g.stage == "Final groups A1" and {g.p1, g.p2} ==
                {"Borisov, Maxim", "Österman, Hans"})
    assert (game.g1, game.g2) == ((4, 2) if game.p1 == "Borisov, Maxim" else (2, 4))
    assert not skips.counts["cross-table name not resolved"]
    assert all(g.stage_type == "roundrobin" for g in p.games)
    borisov = p.players["Borisov, Maxim"]
    assert borisov.ithf and borisov.idpl and borisov.nation == "RUS"
