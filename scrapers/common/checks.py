"""Data checks run on every source's rows before its Parquet is written. A failed check stops the run, so a
known class of id or duplicate bug cannot reach the H2H site again."""

from __future__ import annotations

import re
from collections import defaultdict

import pandas as pd

from .players import fold, strip_nickname


class DataCheckError(ValueError):
    pass


def _words(name: str) -> frozenset[str]:
    return frozenset(fold(strip_nickname(name)).split())


def shared_id_conflicts(df: pd.DataFrame) -> list[tuple]:
    """(TournamentID, player id, name1, name2) where one id carries two names in one tournament that share no
    word after folding accents and word order ('Kirill Storchak' / 'Arseniy Stolyarov'). Spelling variants
    ('Ka Brodacký' / 'Karel Brodacký', 'Skrlep Nejc' / 'Nejc Škrlep') share a word and pass."""
    names: dict[tuple, set[str]] = defaultdict(set)
    for side in ("1", "2"):
        for tid, pid, name in zip(df["TournamentID"], df[f"Player{side}ID"], df[f"Player{side}"]):
            names[(int(tid), int(pid))].add(str(name))
    out = []
    for (tid, pid), ns in sorted(names.items()):
        if len(ns) < 2:
            continue
        ordered = sorted(ns)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                if not (_words(a) & _words(b)):
                    out.append((tid, pid, a, b))
    return out


_SLOT = re.compile(r"/(\d+)-(\d+)/\d+$")


def double_slot_conflicts(df: pd.DataFrame) -> list[tuple]:
    """(StageID, player id, slots) where one id fills two rows of one round-robin cross-table. Uses the row
    numbers in the Trefik SW match ids ('.../<group>/<row>-<col>/<n>'); sources without them are not checked."""
    slots: dict[tuple, set[int]] = defaultdict(set)
    rr = df[df["StageType"] == "roundrobin"]
    for sid, mid, p1, p2 in zip(rr["StageID"], rr["SourceMatchID"], rr["Player1ID"], rr["Player2ID"]):
        m = _SLOT.search(str(mid))
        if not m:
            continue
        slots[(int(sid), int(p1))].add(int(m.group(1)))
        slots[(int(sid), int(p2))].add(int(m.group(2)))
    return [(sid, pid, sorted(s)) for (sid, pid), s in sorted(slots.items()) if len(s) > 1]


def carried_over_conflicts(df: pd.DataFrame) -> list[tuple]:
    """(TournamentID, pair, score) stored in both a basic group and a final group of one tournament. Some are
    real rematches that happen to end with the same score (about 350 of 300k Trefik games), so this list is for
    reports; ``carried_over_stages`` is what fails a run."""
    rr = df[df["StageType"] == "roundrobin"]
    is_final = rr["Stage"].str.contains("Final groups", regex=False)
    seen: dict[tuple, set[bool]] = defaultdict(set)
    for tid, a, b, ga, gb, fin in zip(rr["TournamentID"], rr["Player1ID"], rr["Player2ID"], rr["GoalsPlayer1"],
                                      rr["GoalsPlayer2"], is_final):
        if a > b:
            a, b, ga, gb = b, a, gb, ga
        seen[(int(tid), int(a), int(b), int(ga), int(gb))].add(bool(fin))
    return [k for k, v in sorted(seen.items()) if v == {True, False}]


def carried_over_stages(df: pd.DataFrame, share: float = 0.6) -> list[tuple]:
    """(TournamentID, Stage, pairs that met earlier, of them with the same score) for final-group stages that
    still look carried over: at least ``share`` of the pairs that met earlier in the tournament repeat the score.
    In a stage of real rematches a repeated score is a coincidence (typically 0-20%)."""
    rr = df[df["StageType"] == "roundrobin"]
    out = []
    for tid, t in rr.groupby("TournamentID"):
        fin = t[t["Stage"].str.contains("Final groups", regex=False)]
        for (seq, stage), st in fin.groupby(["StageSequence", "Stage"]):
            earlier: dict[tuple, set] = defaultdict(set)
            prev = t[t["StageSequence"] < seq]
            for a, b, ga, gb in zip(prev["Player1ID"], prev["Player2ID"], prev["GoalsPlayer1"], prev["GoalsPlayer2"]):
                earlier[(a, b)].add((ga, gb))
                earlier[(b, a)].add((gb, ga))
            met = same = 0
            for a, b, ga, gb in zip(st["Player1ID"], st["Player2ID"], st["GoalsPlayer1"], st["GoalsPlayer2"]):
                if (a, b) in earlier:
                    met += 1
                    same += (ga, gb) in earlier[(a, b)]
            if met and same / met >= share:
                out.append((int(tid), stage, met, same))
    return out


def run_checks(df: pd.DataFrame, source: str, carried_over: bool = True) -> None:
    problems = []
    for tid, pid, a, b in shared_id_conflicts(df):
        problems.append(f"id {pid} is both {a!r} and {b!r} in tournament {tid}")
    for sid, pid, s in double_slot_conflicts(df):
        problems.append(f"id {pid} fills rows {s} of stage {sid}")
    if carried_over:
        for tid, stage, met, same in carried_over_stages(df):
            problems.append(f"{stage!r} of tournament {tid} repeats {same} of {met} earlier results (carried over)")
    if problems:
        raise DataCheckError(f"{source}: {len(problems)} data check failure(s):\n  " + "\n  ".join(problems[:50]))


def clear_bad_overtime(rows: list[dict], skips=None) -> list[dict]:
    """An overtime game ends on the first goal, so it is won by exactly one goal. A few source pages mark
    "P" on a 5:1 or a 1:1 game: the flag is a typo on the page and is cleared (the score is kept)."""
    for r in rows:
        if r.get("Overtime") == "Yes" and abs(int(r["GoalsPlayer1"]) - int(r["GoalsPlayer2"])) != 1:
            r["Overtime"] = "No"
            if skips is not None:
                skips.skip("overtime flag cleared (not a one-goal game)",
                           f"{r['TournamentName']} {r['Stage']} {r['GoalsPlayer1']}:{r['GoalsPlayer2']}")
    return rows
