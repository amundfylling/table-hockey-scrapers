"""End-of-run report: rows per tournament, skipped rows by reason, id mapping stats."""

from __future__ import annotations

from collections import Counter

import pandas as pd


class SkipCounter:
    """Counts rows a transform deliberately left out (byes, walkovers, carried-forward results, ...)."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.examples: dict[str, list[str]] = {}

    def skip(self, reason: str, example: str = "") -> None:
        self.counts[reason] += 1
        if example:
            ex = self.examples.setdefault(reason, [])
            if len(ex) < 3:
                ex.append(example)

    def lines(self) -> list[str]:
        if not self.counts:
            return ["  (none)"]
        out = []
        for reason, n in self.counts.most_common():
            ex = "; ".join(self.examples.get(reason, []))
            out.append(f"  {reason}: {n}" + (f"  (e.g. {ex})" if ex else ""))
        return out


def print_report(source: str, df: pd.DataFrame, skips: SkipCounter, id_stats: dict[str, int]) -> None:
    print(f"\n===== {source}: {len(df)} rows, {df['TournamentID'].nunique() if len(df) else 0} tournaments =====")
    if len(df):
        per = (df.groupby(["Date", "TournamentID", "TournamentName"], dropna=False).size()
               .reset_index(name="rows"))
        for r in per.itertuples(index=False):
            print(f"  {r.Date}  {r.TournamentID}  {r.rows:6d}  {r.TournamentName}")
    print("Skipped rows by reason:")
    for line in skips.lines():
        print(line)
    print("Player id mapping (unique players):")
    labels = {
        "ithf_sportscorpion": "via ITHF -> Sportscorpion",
        "ithf_name_sportscorpion": "via ITHF id + name -> Sportscorpion",
        "sportscorpion_name": "via name -> Sportscorpion",
        "ithf_synthetic": "via ITHF synthetic (9M + ithf)",
        "source_local": "source-local",
    }
    for key, label in labels.items():
        print(f"  {label}: {id_stats.get(key, 0)}")
    print(f"  total: {id_stats.get('total', 0)}")
