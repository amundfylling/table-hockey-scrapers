from scrapers.trefik import Parsed, _title_place, dedupe_names, tournament_city
from scrapers.trefik.discover import Listed


def test_title_place_drops_the_date():
    assert _title_place("Třinec 9. duben 2022") == "Třinec"
    assert _title_place("Plzeň, 21. leden 2023") == "Plzeň"
    assert _title_place("Kamenný Újezdec") == "Kamenný Újezdec"


def test_city():
    item = Listed("turnaje2026/mo", "u", 2026, "Olomouc, MO", "Olomouc, MO", "4.10.2025")
    assert tournament_city(item, "") == "Olomouc"
    co = Listed("turnaje2009/co", "u", 2009, "Czech Open", "Czech Open", "")
    assert tournament_city(co, "Czech Open - Praha, 25. duben 2009") == "Praha"


def test_same_name_gets_the_date():
    ps = [Parsed("a", "Czech Cup Plzeň 2003", "2003-09-20", "u"), Parsed("b", "Czech Cup Plzeň 2003", "2003-12-13", "u"),
          Parsed("c", "Czech Cup Brno 2003", "2003-01-01", "u")]
    dedupe_names(ps)
    assert [p.name for p in ps] == ["Czech Cup Plzeň 20.09.2003", "Czech Cup Plzeň 13.12.2003", "Czech Cup Brno 2003"]
