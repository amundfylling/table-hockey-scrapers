"""escore.live: real cached pages of event 45 (Ukraine Cup 2026)."""

import gzip
import json
from collections import Counter
from pathlib import Path

from scrapers.common.report import SkipCounter
from scrapers.escore import event_games, event_name, round_label

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads(gzip.decompress((FIX / name).read_bytes()))


def _event():
    ev = _load("45.json.gz")
    nets = []
    for tab in ev["tabs"]:
        if isinstance(tab["id"], int):
            net = _load(f"45_net{tab['id']}.json.gz")
            net.setdefault("net", {})["_label"] = tab["label"]
            nets.append(net)
    return ev, nets


def test_round_labels():
    assert [round_label(16, r) for r in (1, 2, 3, 4)] == ["1/8", "1/4", "1/2", "Final"]
    assert round_label(12, 1) == "1/8" and round_label(2, 1) == "Final"


def test_event_name_uses_competition():
    ev, _ = _event()
    assert event_name(ev["competitionEvent"], ev["otherEvents"]) == "Ukraine Cup 2026"


def test_games_one_row_per_set():
    ev, nets = _event()
    games = event_games(45, ev, nets, SkipCounter())
    assert len(games) == 197
    assert Counter(g["stage"]["name"] for g in games) == {
        "Basic groups": 156, "Playoff 1/4": 21, "Playoff 1/2": 10, "Playoff Final": 5, "Playoff 3.-4. place": 5}
    players = {p["player_id"]: p["player"]["surname"] for p in ev["participants"]}
    final = [(players[g["p1"]], players[g["p2"]], g["g1"], g["g2"], g["ot"], g["game_no"])
             for g in games if g["stage"]["name"] == "Playoff Final"]
    assert final == [("Umanskyy", "Ignatenko", 2, 4, False, 1), ("Umanskyy", "Ignatenko", 3, 0, False, 2),
                     ("Umanskyy", "Ignatenko", 5, 3, False, 3), ("Umanskyy", "Ignatenko", 3, 2, True, 4),
                     ("Umanskyy", "Ignatenko", 5, 4, True, 5)]
    assert all(g["round"] >= 1 for g in games)
