"""galdahokejs.lv: real cached Trefik SW pages (Amatieru Liga 1.posms 2023, cp1250 bytes under a 1257 label)."""

import gzip
from collections import defaultdict
from pathlib import Path

from scrapers.common import trefik_sw as sw
from scrapers.common.report import SkipCounter
from scrapers.galdahokejs import base_name, decode, event_core, stats_cache, tournament_name
from scrapers.trefik import Parsed, assemble, resolve_groups

RAW = Path(__file__).parent / "fixtures" / "raw"
INDEX = "https://galdahokejs.lv/stats/23AL1/Amatieru_Liga_1.posms_index.php"


def fetch(url):
    path = stats_cache(RAW, url)
    return decode(gzip.decompress(path.read_bytes())) if path.exists() else None


def test_names():
    assert base_name("Rigas Kauss 2024 I (GrDiv)") == "Rigas Kauss 2024"
    assert event_core("Rigas Kauss 2024 I (GrDiv)") == event_core("Rigas Kauss 2024 II (top72)") == "rigas kauss"
    assert tournament_name(Parsed("23LK1/x", "Latvijas Kauss 1.posms", "2023-09-09", "")) == \
        "Latvijas Kauss 1.posms 2023"
    assert tournament_name(Parsed("24EChO/x", "Open Individual (O)", "2024-06-15", "")) == \
        "European Championship 2024 – Open"


def test_cross_table_labels_resolved_from_reference_names():
    html = fetch(INDEX)
    assert "Vazolinš" in fetch(INDEX.replace("_index", "_cross"))  # 0x9a decoded, not U+FFFD
    ev = sw.parse_event_page(html, INDEX)
    assert ev.date.isoformat() == "2023-09-09"
    p = assemble(Parsed("23AL1/x", "Amatieru Liga 1.posms", "2023-09-09", INDEX), sw.collect_pages(INDEX, html, fetch),
                 SkipCounter())
    labels = [r.label for _, g in p.pending_groups for r in g.rows]
    assert len(labels) == 17 and labels[:3] == ["Ra Martužans", "Iv Kirsis", "Ra Ladusans"]
    # No full names on the event's own pages: the Latvian reference names fill in (only unique matches).
    resolve_groups(p, defaultdict(list), SkipCounter(), ["Ladusāns Rauls", "Kirsis Ivars", "Kirsis Maris",
                                                         "Martužans Raitis"])
    games = {(g.p1, g.p2): (g.g1, g.g2) for g in p.games}
    assert games == {("Martužans Raitis", "Kirsis Ivars"): (3, 5), ("Martužans Raitis", "Ladusāns Rauls"): (5, 3),
                     ("Kirsis Ivars", "Ladusāns Rauls"): (3, 3)}
