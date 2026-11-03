from pathlib import Path

from scrapers.common.players import PlayerMapper, fold, load_reference, name_key

FIX = Path(__file__).parent / "fixtures"


def ref():
    # players_data_sample.csv is a real excerpt of Sportscorpion's players_data.csv.
    # ranking_sample.txt follows ranking.txt's documented layout (it could not be downloaded when the test was
    # written); replace it with a real excerpt once stiga.trefik.cz is reachable.
    return load_reference(str(FIX / "players_data_sample.csv"), str(FIX / "ranking_sample.txt"))


def test_fold_and_name_key():
    assert fold("Plešák  Pavel") == "plesak pavel"
    assert fold("Øystein Klippen") == "oystein klippen"
    assert name_key("Plešák Pavel") == name_key("Pavel Plesak")
    assert name_key("Kalniņš Rainers") == name_key("Rainers Kalnins")


def test_ithf_to_sportscorpion_and_synthetic():
    m = PlayerMapper(ref(), "test")
    assert m.resolve("a", ithf="200042.0", local_id=50_000_001) == 391
    assert m.resolve("b", ithf=777, local_id=50_000_002) == 9_000_777
    assert m.resolve("c", local_id=50_000_003) == 50_000_003
    # duplicated RankingID in players_data.csv -> lowest PlayerID
    assert m.resolve("d", ithf=660637, local_id=1) == 1507
    assert m.stats() == {"ithf_sportscorpion": 2, "ithf_synthetic": 1, "sportscorpion_name": 0,
                         "source_local": 1, "total": 4}


def test_ranking_name_match_is_unique_and_nation_aware():
    m = PlayerMapper(ref(), "test")
    assert m.match_ranking("Tmej Petr", nation="CZE") == 70418
    assert m.match_ranking("Kalniņš Rainers", nation="LVA") == 123003  # ISO code accepted
    assert m.match_ranking("Plešák Pavel") is None  # two players, no nation -> ambiguous
    assert m.match_ranking("Plešák Pavel", prefer_nation="CZE") == 123001
    assert m.match_ranking("Plešák Pavel", nation="SVK") == 123002
    assert m.match_ranking("Tmej Petr", nation="LAT") is None


def test_sportscorpion_name_match_with_country(tmp_path):
    m = PlayerMapper(ref(), "test")
    assert m.match_sportscorpion("Bogdans Edijs", "LAT") == 191
    assert m.match_sportscorpion("Bogdans Edijs", "CZE") is None
    assert m.match_sportscorpion("Klippen Oystein", "NOR") is None  # two PlayerIDs -> not unique
    out = tmp_path / "name_matches.csv"
    m.write_name_matches(out)
    text = out.read_text()
    assert "Bogdans Edijs" in text and "Klippen Oystein" in text
