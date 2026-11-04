"""Sportscorpion name fallbacks and the "played each other" guard (rows are real players_data.csv /
ranking.txt lines, 3.11.2026)."""

from pathlib import Path

from scrapers.common.players import PlayerMapper, ReferenceData, parse_players_csv, parse_ranking
from scrapers.common.registry import IdRegistry
from scrapers.trefik import IdResolver, Parsed, PlayerRef, to_rows as trefik_rows

PLAYERS = """PlayerID,Name,RankingID,Country,City,DateOfBirth,Sex
453,Anton Lampi,,Finland,Lohja,06.09.1989,Not set
1022,Andrey Kolybelnikov,,Russia,Moscow,24.06.1980,Not set
4835,Leos Hvizd,70182.0,Czech Republic,Pribram,13.04.1986,Male
9900,Ahti Lampi,100132.0,Finland,Kuopio,24.02.1991,Male
16216,Adam Kalina,,Slovakia,Prešov,01.01.2001,Male
16217,Martin Kalina,,Slovakia,Prešov,01.01.1964,Male
17001,Jan Novak,,Czech Republic,,,Male
17002,Jan Novák,,,,,Male
17003,Petr Svoboda,,Russia,,,Male
"""
RANKING = """Table hockey ranking up to 3.11.2026
Rank\tID_Player\tPlayer\tClub\tNation\tPoints\tPlayer_Value
438\t100904\tAnton Lampi\tTalpelan Taiga\tFIN\t1669\t476
732\t671069\tAdam Kalina\tTHC Hornets Presov\tSVK\t943\t232
1300\t671070\tMartin Kalina\tTHC Hornets Presov\tSVK\t251\t102
1495\t100132\tAhti Lampi\tSpjalerance\tFIN\t176\t788
"""


def ref() -> ReferenceData:
    ithf_map, by_name = parse_players_csv(PLAYERS)
    return ReferenceData(ithf_map, by_name, parse_ranking(RANKING))


def test_ithf_id_unknown_to_sportscorpion_falls_back_to_name_match():
    m = PlayerMapper(ref(), "test")
    # ITHF 671069 has no RankingID in players_data.csv, but "Adam Kalina" (SVK) is PlayerID 16216
    assert m.resolve("a", ithf=671069, local_id=1, name="Kalina Adam") == 16216
    # nation from the source wins; a contradicting one blocks the match
    assert m.resolve("b", ithf=100904, local_id=2, name="Lampi Anton", nation="FIN") == 453
    assert m.resolve("c", ithf=100904, local_id=3, name="Lampi Anton", nation="SWE") == 9_100_904
    # without a name the old rule holds
    assert m.resolve("d", ithf=671070, local_id=4) == 9_671_070
    assert m.stats()["ithf_name_sportscorpion"] == 2
    assert m.stats()["ithf_synthetic"] == 2
    logged = {(e["source_key"], e["method"]): e["result_id"] for e in m.name_log.values()}
    assert logged[("a", "ithf_name_sportscorpion")] == "16216"
    assert logged[("c", "ithf_name_sportscorpion")] == ""


def test_ithf_fallback_ignores_candidate_with_another_persons_ranking_id():
    m = PlayerMapper(ref(), "test")
    # "Ahti Lampi" in Sportscorpion carries RankingID 100132, which ranking.txt gives to Ahti Lampi: a source
    # player named Ahti Lampi with another ITHF id may still be him (duplicate ITHF registration) ...
    assert m.resolve("a", ithf=999999, local_id=1, name="Ahti Lampi", nation="FIN") == 9900
    # ... but not when the name only matches because ranking.txt says the other id is someone else
    r = ref()
    r.ranking_by_id[100132] = ("FIN", "Somebody Else")
    assert PlayerMapper(r, "test").resolve("a", ithf=999999, local_id=1, name="Ahti Lampi", nation="FIN") \
        == 9_999_999


def test_sportscorpion_name_match_rules():
    m = PlayerMapper(ref(), "test")
    assert m.match_sportscorpion("Kolybelnikov Andrey") == 1022            # unique overall, no nation
    assert m.match_sportscorpion("Andrey Kolybelnikov", "RUS") == 1022
    assert m.match_sportscorpion("Andrey Kolybelnikov", "CZE") is None
    # "Jan Novak" (CZE) and "Jan Novák" (no country) fold to the same name: not unique, even with a nation
    assert m.match_sportscorpion("Novák Jan") is None
    assert m.match_sportscorpion("Novák Jan", "CZE") is None
    # Russian country in players_data.csv contradicts a Czech source nation
    assert m.match_sportscorpion("Svoboda Petr", "CZE") is None
    assert m.match_sportscorpion("Svoboda Petr") == 17003


def _trefik_event(players: dict[str, PlayerRef], games: list[tuple[str, str]]) -> Parsed:
    from scrapers.trefik import Game

    p = Parsed("t2024/x", "Czech Cup X 2024", "2024-03-01", "https://stiga.trefik.cz/x")
    p.players = players
    for i, (a, b) in enumerate(games):
        p.games.append(Game("Basic groups A", "roundrobin", 1, 1, None, a, b, 3, 1, False, f"m{i}", p.url))
    return p


def _registries(tmp_path: Path):
    return (IdRegistry(tmp_path / "p.csv", 21_000_001, ("name",)), IdRegistry(tmp_path / "t.csv", 3_000_000_001,
            ("name",)), IdRegistry(tmp_path / "s.csv", 3_100_000_001, ("name",)))


def test_trefik_falls_back_to_sportscorpion_name(tmp_path):
    players = {"Kolybelnikov Andrey": PlayerRef("Kolybelnikov Andrey", idpl=447),
               "Hvižď Leoš": PlayerRef("Hvižď Leoš"),
               "Neznámý Hráč": PlayerRef("Neznámý Hráč")}
    p = _trefik_event(players, [("Kolybelnikov Andrey", "Hvižď Leoš"), ("Hvižď Leoš", "Neznámý Hráč")])
    p_reg, t_reg, s_reg = _registries(tmp_path)
    mapper = PlayerMapper(ref(), "trefik")
    rows = trefik_rows([p], IdResolver([p], mapper, p_reg), t_reg, s_reg)
    ids = {r["Player1"]: r["Player1ID"] for r in rows} | {r["Player2"]: r["Player2ID"] for r in rows}
    assert ids["Andrey Kolybelnikov"] == 1022
    assert ids["Leoš Hvižď"] == 4835           # Sportscorpion row has RankingID 70182, still matched by name
    assert ids["Hráč Neznámý"] == 21_000_002   # no match: local id, registry numbering unchanged
    assert mapper.stats()["sportscorpion_name"] == 2


def test_trefik_name_match_needs_one_trefik_player_with_that_name(tmp_path):
    a = PlayerRef("Kolybelnikov Andrey", idpl=1)
    b = PlayerRef("Kolybelnikov Andrey", idpl=2)
    p1 = _trefik_event({"Kolybelnikov Andrey": a, "Neznámý Hráč": PlayerRef("Neznámý Hráč")},
                       [("Kolybelnikov Andrey", "Neznámý Hráč")])
    p2 = _trefik_event({"Kolybelnikov Andrey": b}, [])
    p_reg, _, _ = _registries(tmp_path)
    resolver = IdResolver([p1, p2], PlayerMapper(ref(), "trefik"), p_reg)
    assert resolver.resolve(a) == 20_000_001


def test_played_each_other_guard(tmp_path):
    # "Kolybelnikov Andrey" (idpl 5) name-matches Sportscorpion 1022. In the same tournament he plays
    # "Kolybelnikov A." (idpl 6) whose ITHF id also leads to 1022. Same id on both sides of a game = two
    # people, so the name-based mapping is refused and idpl 5 keeps his Trefik id.
    r = ref()
    r.ithf_to_player[555555] = 1022
    players = {"Kolybelnikov Andrey": PlayerRef("Kolybelnikov Andrey", idpl=5),
               "Kolybelnikov A.": PlayerRef("Kolybelnikov A.", idpl=6, ithf=555555),
               "Hvižď Leoš": PlayerRef("Hvižď Leoš")}
    p = _trefik_event(players, [("Kolybelnikov Andrey", "Kolybelnikov A."), ("Kolybelnikov Andrey", "Hvižď Leoš"),
                                ("Kolybelnikov A.", "Hvižď Leoš")])
    p_reg, t_reg, s_reg = _registries(tmp_path)
    mapper = PlayerMapper(r, "trefik")
    rows = trefik_rows([p], IdResolver([p], mapper, p_reg), t_reg, s_reg)
    assert len(rows) == 3  # the game between them is no longer lost as a self-game
    assert {(x["Player1ID"], x["Player2ID"]) for x in rows} == {(20_000_005, 1022), (20_000_005, 4835),
                                                               (1022, 4835)}
    assert mapper.blocked == {("idpl:5", 1022)}
    assert mapper.seen["idpl:5"] == "source_local" and mapper.seen["idpl:6"] == "ithf_sportscorpion"
    out = tmp_path / "name_matches.csv"
    mapper.write_name_matches(out)
    text = out.read_text()
    assert "rejected_played_each_other" in text and "refused: played each other" in text


def test_guard_ignores_players_who_never_meet():
    m = PlayerMapper(ref(), "test")
    m.begin_tournament(1)
    a = m.resolve("a", local_id=1, sc_player_id=1022)
    b = m.resolve("b", local_id=2, ithf=671069, name="Adam Kalina")
    m.played(a, b)
    m.begin_tournament(2)
    c = m.resolve("c", local_id=3, sc_player_id=1022)
    m.played(c, 999)
    assert not m.apply_guard() and not m.blocked
