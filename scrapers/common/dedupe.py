"""Cross-source check: flag tournaments emitted by two sources with the same date (±1 day) and a similar name."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from .players import fold

# Words that say nothing about which event it is.
_STOP = {"the", "of", "and", "open", "cup", "tournament", "turnir", "turnirs", "turnaj", "kauss", "posms",
         "kolo", "round", "stage", "etaps", "open", "individual"}


def _core(name: str) -> str:
    text = fold(name)
    text = re.sub(r"\b(19|20)\d{2}(/\d{2,4})?\b", " ", text)  # years
    return " ".join(t for t in text.split() if t not in _STOP)


def similarity(a: str, b: str) -> float:
    ca, cb = _core(a), _core(b)
    if not ca or not cb:
        return 0.0
    ta, tb = set(ca.split()), set(cb.split())
    jaccard = len(ta & tb) / len(ta | tb)
    return max(jaccard, SequenceMatcher(None, ca, cb).ratio())


def tournaments(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Source", "TournamentID", "TournamentName", "Date", "SourceTournamentID"])
    return (df.groupby(["Source", "TournamentID"], as_index=False)
              .agg(TournamentName=("TournamentName", "first"), Date=("Date", "min"),
                   SourceTournamentID=("SourceTournamentID", "first")))


def find_duplicates(df: pd.DataFrame, threshold: float = 0.6, max_days: int = 1) -> pd.DataFrame:
    """Pairs of tournaments from *different* sources within ``max_days`` and with name similarity >= threshold."""
    t = tournaments(df)
    out = []
    if t.empty:
        return pd.DataFrame(columns=["SourceA", "TournamentA", "DateA", "SourceB", "TournamentB", "DateB",
                                     "Similarity"])
    t = t.assign(When=pd.to_datetime(t["Date"])).sort_values("When").reset_index(drop=True)
    rows = list(t.itertuples(index=False))
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if (b.When - a.When).days > max_days:
                break
            if a.Source == b.Source:
                continue
            sim = similarity(a.TournamentName, b.TournamentName)
            if sim >= threshold:
                out.append({"SourceA": a.Source, "TournamentA": f"{a.TournamentName} [{a.SourceTournamentID}]",
                            "DateA": a.Date, "SourceB": b.Source,
                            "TournamentB": f"{b.TournamentName} [{b.SourceTournamentID}]", "DateB": b.Date,
                            "Similarity": round(sim, 2)})
    return pd.DataFrame(out, columns=["SourceA", "TournamentA", "DateA", "SourceB", "TournamentB", "DateB",
                                      "Similarity"])


def check_and_report(df: pd.DataFrame, report_path: Path | None = None) -> pd.DataFrame:
    dups = find_duplicates(df)
    print(f"\n===== Cross-source duplicate check: {len(dups)} suspicious pair(s) =====")
    for r in dups.itertuples(index=False):
        print(f"  {r.DateA} {r.SourceA}: {r.TournamentA}  <->  {r.DateB} {r.SourceB}: {r.TournamentB}"
              f"  (sim {r.Similarity})")
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        dups.to_csv(report_path, index=False, lineterminator="\n")
    return dups
