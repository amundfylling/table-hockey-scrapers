"""Regression tests for the H2H data audit (shared ids, double slots, carried-over games, names)."""

import pandas as pd
import pytest

from scrapers.common import trefik_sw as sw
from scrapers.common.checks import (DataCheckError, carried_over_conflicts, carried_over_stages, clear_bad_overtime,
                                    double_slot_conflicts, run_checks, shared_id_conflicts)
from scrapers.common.dedupe import drop_carried_over
from scrapers.common.players import PlayerMapper, ReferenceData, base_key, name_key, parse_ranking
from scrapers.common.schema import to_frame


def test_participants_skip_layout_row_that_wraps_the_list():
    # Czech Open 2022 list: one outer <tr> wraps every player row; read as a row it paired Brodacký's ITHF id
    # with Čermák's idpl (and gave two people one id).
    html = """<table><tr><td><table>
      <tr><td><a href="x/overview_co.aspx?idpl=1984">Karel Brodacký</a></td>
          <td><a href="https://stiga.trefik.cz/ithf/ranking/player.aspx?ID=673226">1909</a></td></tr>
      <tr><td><a href="x/overview_co.aspx?idpl=1982">Jan Čermák</a></td>
          <td><a href="https://stiga.trefik.cz/ithf/ranking/player.aspx?ID=">9999</a></td></tr>
    </table></td></tr></table>"""
    assert sorted(sw.parse_participants(html)) == [(1982, None, "Jan Čermák"), (1984, 673226, "Karel Brodacký")]


def test_short_labels_prefer_a_real_prefix_over_the_nickname_rule():
    g = sw.Group("final", "3.Liga", [sw.CrossRow("Marg Ābele", ["*", "1:2"]), sw.CrossRow("Mark Ābele", ["2:1", "*"])])
    sw.resolve_group_names(g, ["Ābele Margarita", "Ābele Markuss", "Marg Ābele"])
    assert [r.full for r in g.rows] == ["Ābele Margarita", "Ābele Markuss"]
    assert sw.abbrev_matches("Vojta Novák", "Novák Vojtěch")  # the nickname rule still works on its own


def _ref(players: list[tuple], ranking: str = "", archive: dict | None = None) -> ReferenceData:
    by_name: dict = {}
    ithf_map = {}
    for pid, name, rid, country in players:
        by_name.setdefault(name_key(name), []).append((pid, country, name, rid))
        if rid:
            ithf_map[rid] = pid
    return ReferenceData(ithf_map, by_name, parse_ranking(ranking), archive_by_name=archive or {})


def test_quoted_nicknames_are_ignored():
    assert name_key('Raivis "The Cobra" Miglinieks') == name_key("Raivis Miglinieks")
    assert name_key('Eike Rompa "Fury"') == name_key("Rompa Eike")
    ref = _ref([(8566, 'Raivis "The Cobra" Miglinieks', 659307, "Latvia")],
               'Rank\tID_Player\tPlayer\tClub\tNation\n4\t659307\tRaivis Miglinieks "The Cobra"\tBJC\tLAT\n')
    m = PlayerMapper(ref, "t")
    ithf = m.match_ranking("Raivis Miglinieks", prefer_nation="LAT", source_key="k")
    assert m.resolve("k", ithf=ithf, local_id=1) == 8566


def test_suffix_match_only_when_unique_and_unambiguous():
    ref = _ref([(14661, "Michael Moravec ml.", None, "Czech Republic"),
                (2585, "Zdenek Matoušek ml.", 70057, "Czech Republic")],
               "Rank\tID_Player\tPlayer\tClub\tNation\n1\t70057\tZdenek Matousek ml.\tZ\tCZE\n"
               "2\t70029\tZdenek Matousek st.\tZ\tCZE\n")
    m = PlayerMapper(ref, "t")
    assert m.match_sportscorpion("Michael Moravec", "CZE") == 14661
    assert m.match_sportscorpion("Michael Moravec st.", "CZE") is None  # the source name has its own suffix
    assert m.match_sportscorpion("Zdeněk Matoušek", "CZE") is None  # st. 70029 exists too: father or son?
    assert base_key("Martin Moravec St.") == name_key("Martin Moravec")


def test_archive_gives_inactive_players_their_ithf_id_but_not_an_ambiguous_one():
    archive = {name_key("Karel Konecny"): [(70067, "CZE", "Karel Konecny")],
               name_key("Jiri Chylik"): [(79394, "CZE", "Jiri Chylik")]}
    ref = _ref([], "Rank\tID_Player\tPlayer\tClub\tNation\n1\t79394\tJiri Chylik ml.\tZ\tCZE\n"
                   "2\t79393\tJiri Chylik st.\tZ\tCZE\n", archive)
    m = PlayerMapper(ref, "t")
    assert m.match_ranking("Karel Konečný", prefer_nation="CZE") == 70067
    assert m.resolve("k", ithf=70067, local_id=21000298) == 9_070_067
    assert m.match_ranking("Jiří Chylík", prefer_nation="CZE") is None


def _row(**kw):
    base = dict(StageID=1, Player1="A B", Player1ID=1, Player2="C D", Player2ID=2, GoalsPlayer1=3, GoalsPlayer2=1,
                Overtime="No", Stage="Basic groups 1", RoundNumber=1, PlayoffGameNumber=None, Date="2025-01-02",
                TournamentName="T", TournamentID=10, StageSequence=1, StageType="roundrobin", Source="s",
                SourceTournamentID="t", SourceStageID="g", SourceMatchID="t/basic/1/1-2/1", Country="Latvia")
    base.update(kw)
    return base


def test_check_fails_on_one_id_with_two_unrelated_names():
    df = to_frame([_row(), _row(Player1="Arseniy Stolyarov", Player2="Kirill Storchak", Player2ID=3, SourceMatchID="m2")])
    assert shared_id_conflicts(df) == [(10, 1, "A B", "Arseniy Stolyarov")]
    with pytest.raises(DataCheckError):
        run_checks(df, "test")
    ok = to_frame([_row(Player1="Ka Brodacký"), _row(Player1="Karel Brodacký", Player2ID=3, SourceMatchID="m2")])
    assert shared_id_conflicts(ok) == []


def test_check_fails_when_one_id_fills_two_rows_of_a_group():
    df = to_frame([_row(SourceMatchID="t/final/3/9-17/1", Player2ID=5),
                   _row(SourceMatchID="t/final/3/14-17/1", Player2ID=6)])
    assert double_slot_conflicts(df) == [(1, 1, [9, 14])]


def test_carried_over_games_are_dropped_only_in_carry_over_stages():
    basic = [_row(Player1ID=1, Player2ID=i, GoalsPlayer1=i, SourceMatchID=f"b{i}") for i in range(2, 7)]
    copied = [_row(Player1ID=1, Player2ID=i, GoalsPlayer1=i, SourceMatchID=f"f{i}", Stage="Final groups A",
                   StageSequence=2) for i in range(2, 6)]
    rematch = [_row(Player1ID=i, Player2ID=1, GoalsPlayer2=i, GoalsPlayer1=0, SourceMatchID=f"r{i}",
                    Stage="Final groups B", StageSequence=3) for i in (2, 3, 4)]
    rematch[0]["GoalsPlayer1"], rematch[0]["GoalsPlayer2"] = 2, 1  # one coincidence among real rematches
    rows = drop_carried_over(basic + copied + rematch)
    assert not [r for r in rows if r["Stage"] == "Final groups A"]  # 4/4 repeat the score: copies
    assert len([r for r in rows if r["Stage"] == "Final groups B"]) == 3  # 1/3 repeat: real games stay
    assert carried_over_conflicts(to_frame(basic + copied)) != []
    assert carried_over_stages(to_frame(basic + copied)) == [(10, "Final groups A", 4, 4)]
    assert carried_over_stages(to_frame(rows)) == []


def test_impossible_overtime_flags_are_cleared():
    rows = clear_bad_overtime([_row(Overtime="Yes", GoalsPlayer1=5, GoalsPlayer2=1),
                               _row(Overtime="Yes", GoalsPlayer1=1, GoalsPlayer2=1),
                               _row(Overtime="Yes", GoalsPlayer1=3, GoalsPlayer2=2)])
    assert [r["Overtime"] for r in rows] == ["No", "No", "Yes"]
