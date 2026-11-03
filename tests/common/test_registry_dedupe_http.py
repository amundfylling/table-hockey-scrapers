import pandas as pd

from scrapers.common.dedupe import find_duplicates
from scrapers.common.http import decode_html
from scrapers.common.registry import IdRegistry


def test_registry_is_stable(tmp_path):
    path = tmp_path / "ids.csv"
    r = IdRegistry(path, first=3_000_000_001, extra_fields=("name",))
    assert r.get("turnaje2023/co2023", name="Czech Open") == 3_000_000_001
    assert r.get("turnaje2025/cheb") == 3_000_000_002
    assert r.get("turnaje2023/co2023") == 3_000_000_001
    r.save()
    r2 = IdRegistry(path, first=3_000_000_001, extra_fields=("name",))
    assert r2.lookup("turnaje2025/cheb") == 3_000_000_002
    assert r2.get("new") == 3_000_000_003
    assert "Czech Open" in path.read_text()


def _t(source, tid, name, date):
    return {"Source": source, "TournamentID": tid, "TournamentName": name, "Date": date,
            "SourceTournamentID": str(tid)}


def test_duplicate_check_flags_same_event_across_sources():
    df = pd.DataFrame([
        _t("galdahokejs.lv", 1, "Riga Cup 2025", "2025-12-06"),
        _t("escore.live", 2, "25th Riga Cup", "2025-12-07"),
        _t("escore.live", 3, "Latvian Cup 2025/26 #2", "2025-12-07"),
        _t("stiga.trefik.cz", 4, "Czech Open 2025", "2025-04-19"),
        _t("galdahokejs.lv", 5, "Riga Cup 2024", "2024-12-07"),  # a year apart: not flagged
    ])
    dups = find_duplicates(df)
    assert len(dups) == 1
    assert {dups.iloc[0].SourceA, dups.iloc[0].SourceB} == {"galdahokejs.lv", "escore.live"}


def test_duplicate_check_ignores_same_source():
    df = pd.DataFrame([_t("escore.live", 1, "Latvian Cup #1", "2026-01-10"),
                       _t("escore.live", 2, "Latvian Cup #1 Juniors", "2026-01-10")])
    assert find_duplicates(df).empty


def test_decode_html_detects_encoding():
    assert decode_html('<meta charset="windows-1250">Plešák'.encode("cp1250")).endswith("Plešák")
    assert decode_html("Kalniņš".encode("utf-8")) == "Kalniņš"
    assert decode_html("Kalniņš".encode("cp1257"), fallbacks=("utf-8", "windows-1257")) == "Kalniņš"
