"""Names that still have more than one player id across Sportscorpion and our Parquets.

Written by ``python -m scrapers.all`` to ``data/player_id_report.csv`` so the remaining cases can be merged by
hand in the H2H site's ``aliases.json``. A name counts as the same when it folds to the same order-free token
set ("Plešák Pavel" = "Pavel Plesak"). Names whose ids are all Sportscorpion PlayerIDs are left out (homonyms
there, not ours to fix).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd

from .players import ITHF_OFFSET, ReferenceData, name_key

FIELDS = ["name", "n_ids", "ids", "details"]


def id_kind(pid: int) -> str:
    if pid >= 20_000_000:
        return "local"
    if pid >= ITHF_OFFSET:
        return "ithf_synthetic"
    return "sportscorpion"


def build(frames: dict[str, pd.DataFrame], ref: ReferenceData) -> pd.DataFrame:
    # name key -> id -> {"names": set, "games": {source: n}, "country": str}
    found: dict[frozenset, dict[int, dict]] = defaultdict(dict)
    for source, df in frames.items():
        if df is None or not len(df):
            continue
        both = pd.concat([df[["Player1", "Player1ID"]].set_axis(["name", "id"], axis=1),
                          df[["Player2", "Player2ID"]].set_axis(["name", "id"], axis=1)])
        counts = both.groupby(["name", "id"]).size()
        for (name, pid), n in counts.items():
            key = name_key(name)
            if not key:
                continue
            e = found[key].setdefault(int(pid), {"names": set(), "games": defaultdict(int), "country": ""})
            e["names"].add(name)
            e["games"][source] += int(n)
    rows = []
    for key, ids in found.items():
        for pid, country, name, _rid in ref.sc_by_name.get(key, []):
            e = ids.setdefault(pid, {"names": set(), "games": defaultdict(int), "country": ""})
            e["names"].add(name)
            e["country"] = country
            e["games"].setdefault("players_data.csv", 0)
        # all ids are Sportscorpion PlayerIDs: homonyms in players_data.csv, nothing to merge on our side
        if len(ids) < 2 or all("players_data.csv" in e["games"] for e in ids.values()):
            continue
        parts, total = [], 0
        for pid in sorted(ids):
            e = ids[pid]
            games = ", ".join(f"{s} {n}" for s, n in sorted(e["games"].items()) if s != "players_data.csv")
            total += sum(e["games"].values())
            in_sc = "players_data.csv" in e["games"]
            parts.append(f"{pid} ({id_kind(pid)}{', in players_data.csv' if in_sc else ''}"
                         f"{', ' + e['country'] if e['country'] else ''}"
                         f"{'; ' + games if games else ''}; as {' / '.join(sorted(e['names']))})")
        name = sorted({n for e in ids.values() for n in e["names"]})[0]
        rows.append({"name": name, "n_ids": len(ids), "ids": " ".join(str(p) for p in sorted(ids)),
                     "details": " | ".join(parts), "_games": total})
    out = pd.DataFrame(rows, columns=[*FIELDS, "_games"])
    out = out.sort_values(["_games", "name"], ascending=[False, True]).drop(columns="_games")
    return out.reset_index(drop=True)


def write(data_dir: Path, sources: list[str], ref: ReferenceData) -> pd.DataFrame:
    frames = {}
    for s in sources:
        path = Path(data_dir) / f"{s}_results.parquet"
        if path.exists():
            frames[s] = pd.read_parquet(path, columns=["Player1", "Player1ID", "Player2", "Player2ID"])
    report = build(frames, ref)
    report.to_csv(Path(data_dir) / "player_id_report.csv", index=False, lineterminator="\n")
    print(f"\nNames with more than one player id (Sportscorpion + Parquets): {len(report)} "
          f"-> data/player_id_report.csv")
    return report
