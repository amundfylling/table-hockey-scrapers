"""One-off backfill of ITHF events archived on the Wayback Machine (ithf.info, Trefik SW pages).

    python -m scrapers.ithf_archive.fetch      # download the pages (web.archive.org) into data/ithf_archive/<event>/raw
    python -m scrapers.ithf_archive            # parse the saved pages -> data/ithf_archive_results.parquet

Not part of the nightly workflow: the events are finished and the pages never change, so the Parquet is built once
and committed. `python -m scrapers.all --combine-only` includes it in all_results.parquet.

Covered: World Championship 2017, Liberec (Open, Women, Juniors, Veterans, 50+, U13; team events are skipped).
The pages are Trefik SW exports, parsed with the shared parser and the trefik module's assembly code. Player
names on ithf.info are first name first; they are stored surname-first internally, as Trefik's code expects.
Trefik ``idpl`` links point at stiga.trefik.cz's player database, so local ids are the trefik module's
20_000_000 + idpl.

Only group-stage games are kept (basic and final groups); play-off games are left out, as asked: bordshockey.net,
which the H2H site already ingests, has the 2017 play-offs.
"""

from __future__ import annotations

import gzip
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..common import trefik_sw as sw
from ..common.checks import clear_bad_overtime, run_checks
from ..common.context import RunContext
from ..common.dedupe import drop_carried_over
from ..common.players import PlayerMapper
from ..common.registry import IdRegistry
from ..common.report import SkipCounter, print_report
from ..common.schema import to_frame, write_parquet
from ..trefik import IdResolver, Parsed, assemble, resolve_groups, to_rows
from ..trefik.discover import decode

log = logging.getLogger(__name__)

SOURCE = "ithf.info (Wayback Machine)"
OUTPUT = "ithf_archive_results.parquet"
TOURNAMENT_BASE = 7_000_000_000
STAGE_BASE = 7_100_000_000
LOCAL_BASE = 60_000_000
# pages that hold games or player lists; *_inter / *_off / *_def are statistics tables
RESULT_PAGE = re.compile(r"_(list|wr|ranking|krizb|krizf|cross_\d+|umisteni)\.aspx$")  # umisteni: names/ids only


@dataclass(frozen=True)
class Event:
    key: str                 # folder under data/ithf_archive/
    base_url: str            # the original site's folder
    name: str
    date: str                # ISO date; the pages carry none (see README)
    country: str
    city: str
    categories: tuple[tuple[str, str], ...]   # (page prefix, name suffix)


EVENTS = [
    Event("wc2017", "https://www.ithf.info/stiga/turnaje2017/ms/", "World Championship 2017", "2017-06-16",
          "Czech Republic", "Liberec",
          (("open", ""), ("ladies", " – Women"), ("juniors", " – Juniors"), ("veterans", " – Veterans"),
           ("50", " – 50+"), ("u13", " – U13"))),
]


def surname_first(name: str) -> str:
    """'Zdeněk Matoušek ml.' -> 'Matoušek ml., Zdeněk' (trefik_sw.display_name turns it back)."""
    parts = name.split()
    gen = ""
    # generation marks printed first: "ml. Jiří Chylík" -> "Chylík ml., Jiří", "I Martin Vépy" -> "Vépy I, Martin"
    if len(parts) > 2 and parts[0].lower().rstrip(".") in ("ml", "st", "i", "ii", "iii"):
        gen, parts = " " + parts[0], parts[1:]
    if len(parts) < 2 or "," in name:
        return name
    return f"{' '.join(parts[1:])}{gen}, {parts[0]}"


def load_pages(raw: Path, ev: Event, prefix: str) -> dict[str, str]:
    pages = {}
    for path in sorted(raw.glob(f"{prefix}_*.aspx.gz")):
        key = path.name[:-3]
        if RESULT_PAGE.search(key) and path.stat().st_size:
            pages[ev.base_url + key] = decode(gzip.decompress(path.read_bytes()))
    # the participants list first: its spelling is kept when pages differ
    return dict(sorted(pages.items(), key=lambda kv: not kv[0].endswith("_list.aspx")))


def parse_category(raw: Path, ev: Event, prefix: str, suffix: str, skips: SkipCounter) -> Parsed | None:
    pages = load_pages(raw, ev, prefix)
    key = f"{ev.key}/{prefix}"
    if not pages:
        skips.skip("category without saved pages", key)
        return None
    parsed = Parsed(key, ev.name + suffix, ev.date, ev.base_url + f"{prefix}_list.aspx", country=ev.country,
                    city=ev.city)
    assemble(parsed, pages, skips)
    return parsed


def finish_category(parsed: Parsed, event_names: list[str], skips: SkipCounter) -> Parsed | None:
    # labels missing from the category's own lists (two veterans who played the Open basic groups) are matched
    # against the names of the event's other categories
    resolve_groups(parsed, {int(parsed.date[:4]): event_names}, skips)
    # nation: the club column of the participants list is the nation code on ithf.info
    for ref in parsed.players.values():
        if ref.club and re.fullmatch(r"[A-Z]{3}", ref.club):
            ref.nation, ref.club = ref.club, None
    # group stage only: play-off games (and the play-off-only players) are left out
    for g in parsed.games:
        if g.stage_type == "playoff":
            skips.skip("play-off game (group stage only)", f"{parsed.key} {g.stage}")
    parsed.games = [g for g in parsed.games if g.stage_type != "playoff"]
    _to_surname_first(parsed)
    return parsed if parsed.games else None


def _to_surname_first(parsed: Parsed) -> None:
    rename = {n: surname_first(n) for n in parsed.players}
    for g in parsed.games:
        rename.setdefault(g.p1, surname_first(g.p1))
        rename.setdefault(g.p2, surname_first(g.p2))
        g.p1, g.p2 = rename[g.p1], rename[g.p2]
    players = {}
    for n, ref in parsed.players.items():
        ref.name = rename[n]
        players[ref.name] = ref
    parsed.players = players


def run(ctx: RunContext) -> pd.DataFrame:
    sdir = ctx.source_dir("ithf_archive")
    skips = SkipCounter()
    parsed: list[Parsed] = []
    for ev in EVENTS:
        raw = sdir / ev.key / "raw"
        found = [p for prefix, suffix in ev.categories if (p := parse_category(raw, ev, prefix, suffix, skips))]
        names = sorted({n for p in found for n in p.players})
        for p in found:
            if finish_category(p, names, skips):
                parsed.append(p)
            else:
                skips.skip("category without games", p.key)
    t_reg = IdRegistry(sdir / "tournament_ids.csv", TOURNAMENT_BASE + 1, ("name",))
    s_reg = IdRegistry(sdir / "stage_ids.csv", STAGE_BASE + 1, ("name",))
    p_reg = IdRegistry(sdir / "player_ids.csv", LOCAL_BASE + 1, ("name",))
    mapper = PlayerMapper(ctx.ref, "ithf_archive")
    resolver = IdResolver(parsed, mapper, p_reg)
    rows = to_rows(parsed, resolver, t_reg, s_reg)
    for r in rows:
        r["Source"] = SOURCE
    rows = clear_bad_overtime(drop_carried_over(rows, skips), skips)
    df = to_frame(rows)
    run_checks(df, SOURCE)
    write_parquet(df, ctx.data_dir / OUTPUT)
    for reg in (t_reg, s_reg, p_reg):
        reg.save()
    mapper.write_name_matches(sdir / "name_matches.csv")
    print_report(SOURCE, df, skips, mapper.stats())
    return df
