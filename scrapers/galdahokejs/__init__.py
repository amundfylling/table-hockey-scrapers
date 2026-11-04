"""Scraper for galdahokejs.lv: Latvian events 2022-05-01 .. 2025-11-30 published as Trefik SW exports.

    python -m scrapers.galdahokejs [--offline]

The Joomla section pages (Latvian Championship, Latvian Cup, Riga Cup, Latvia Open, ...) link to Trefik SW
folders under /stats/<folder>/ (<Name>_index.php, <Name>_cross.php, <Name>_playoff.php). Each folder (or several
folders of one event, e.g. Riga Cup qualification + main + top 72) becomes one tournament, parsed with the same
Trefik SW parser as stiga.trefik.cz. Google Sheets results are listed in data/galdahokejs/google_sheets.csv but
not parsed (see README). Events outside the window, or already on Sportscorpion, are skipped and logged.
"""

from __future__ import annotations

import csv
import logging
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

from ..common import trefik_sw as sw
from ..common.context import RunContext
from ..common.http import decode_html
from ..common.overlaps import near_date, sportscorpion_tournaments
from ..common.players import PlayerMapper, fold
from ..common.registry import IdRegistry
from ..common.report import SkipCounter, print_report
from ..common.schema import to_frame, write_parquet
from ..trefik import Parsed, assemble, resolve_groups
from .discover import crawl_pages

log = logging.getLogger(__name__)

SOURCE = "galdahokejs.lv"
OUTPUT = "galdahokejs_results.parquet"
TOURNAMENT_BASE = 6_000_000_000
STAGE_BASE = 6_100_000_000
LOCAL_BASE = 50_000_000
WINDOW = (date(2022, 5, 1), date(2025, 11, 30))
STATS = "https://galdahokejs.lv/stats/"
TEAM_EVENT = re.compile(r"kom(and|\b|$)|teams?\b|\((JT|OT|VT|WT)\)|E[Cc]h(JT|OT|VT|WT)$", re.I)


def stats_cache(raw_dir: Path, url: str) -> Path:
    rel = urlsplit(url).path.split("/stats/", 1)[1]
    return raw_dir / "stats" / (rel + ".gz")


def decode(data: bytes) -> str:
    return decode_html(data, fallbacks=("utf-8", "windows-1257", "windows-1250"))


def folder_events(links: set[str]) -> list[str]:
    """Index pages of a folder: one per distinct '<Name>_' prefix among the linked pages."""
    out = set()
    for url in links:
        name = url.rsplit("/", 1)[1]
        m = re.match(r"(.+?)_(index|cross|playoff|tour_off|tour_def|ranking|list|krizB|krizF|umisteni)\b", name, re.I)
        if m:
            out.add(url.rsplit("/", 1)[0] + "/" + m.group(1) + "_index.php")
    return sorted(out)


def event_core(title: str) -> str:
    """'Riga Cup 2025 - Main, 6. December 2025' -> 'riga cup' (used to merge folders of one event)."""
    name = base_name(title.split(",", 1)[0])
    name = re.sub(r"\b(19|20)\d\d\b", " ", sw.ascii_fold(name))
    name = re.sub(r"\b(qualification|kvalifikacija|main|top ?\d+|final|finals|playoff|stage|grupas?)\b", " ", name)
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", name).split())


def crawl(ctx: RunContext, skips: SkipCounter) -> list[Parsed]:
    sdir = ctx.source_dir("galdahokejs")
    raw = sdir / "raw"
    found = crawl_pages(ctx.client, raw, offline=ctx.offline)
    _write_sheets(found.sheets, sdir / "google_sheets.csv")

    def fetch(url: str) -> str | None:
        data = ctx.client.get_bytes(url, stats_cache(raw, url), offline=ctx.offline)
        return decode(data) if data else None

    parsed_by_index: list[Parsed] = []
    for folder, links in sorted(found.stats.items()):
        for index_url in folder_events(links):
            if TEAM_EVENT.search(folder) or TEAM_EVENT.search(index_url.rsplit("/", 1)[1]):
                skips.skip("team championship (not individual games)", index_url.split("/stats/", 1)[1])
                continue
            html = fetch(index_url)
            if not html:
                skips.skip("stats index page missing", index_url)
                continue
            ev = sw.parse_event_page(html, index_url)
            if ev.date is None:
                skips.skip("event without a date", index_url)
                continue
            key = index_url.split("/stats/", 1)[1]
            p = Parsed(key, ev.title.split(",", 1)[0].strip() or folder, ev.date.isoformat(), index_url)
            pages = sw.collect_pages(index_url, html, fetch)
            parsed_by_index.append(assemble(p, pages, skips))

    events = merge_multi_folder(parsed_by_index)
    kept = []
    sc = _sportscorpion_latvia(ctx, skips)
    for p in events:
        when = date.fromisoformat(p.date)
        if not (WINDOW[0] <= when <= WINDOW[1]):
            skips.skip("outside 2022-05-01 .. 2025-11-30 (other sources)", f"{p.date} {p.name}")
            continue
        clash = [r for r in sc if near_date(p.date, r[1])]
        if clash:
            skips.skip("also on Sportscorpion", f"{p.date} {p.name} = {clash[0][0]}")
            log.info("skip %s %s: on Sportscorpion as %s", p.date, p.name, clash[0][0])
            continue
        p.name = tournament_name(p)
        kept.append(p)
    pool = defaultdict(list)
    for p in kept:
        pool[int(p.date[:4])].extend(p.players)
    reference = latvian_reference_names(ctx)
    out = []
    for p in kept:
        resolve_groups(p, pool, skips, reference)
        if p.games:
            out.append(p)
        else:
            skips.skip("event without games", p.key)
    return out


ECH_FOLDER = re.compile(r"^(\d\d)ECh(?!Ch)", re.I)


def tournament_name(p: Parsed) -> str:
    """'Open Individual (O)' in folder 24EChO -> 'European Championship 2024 – Open'; a year is added when the
    title has none ('Latvijas Kauss 1.posms' -> 'Latvijas Kauss 1.posms 2023')."""
    name = " ".join(p.name.split())
    year = p.date[:4]
    if ECH_FOLDER.match(p.key):
        cat = re.sub(r"\s*\([^)]*\)", "", name)
        cat = re.sub(r"\bIndividual\b", "", cat).strip()
        return f"European Championship {year} – {cat}"
    if not re.search(r"\b(19|20)\d\d\b", name):
        name = f"{name} {year}"
    return name


def latvian_reference_names(ctx: RunContext) -> list[str]:
    """Latvian players from players_data.csv and ranking.txt as 'Surname First' (Trefik order), used when an
    event's cross-table labels ('Ra Ladusans') have no full name anywhere on galdahokejs.lv."""
    names = []
    for entries in ctx.ref.sc_by_name.values():
        names += [e[2] for e in entries if e[1].strip().lower() == "latvia"]
    for entries in ctx.ref.ranking_by_name.values():
        names += [e[2] for e in entries if e[1] == "LAT"]
    out = []
    for n in names:
        parts = re.sub(r'"[^"]*"', " ", n).split()
        if len(parts) >= 2:
            out.append(" ".join([parts[-1], *parts[:-1]]))
    return out


def base_name(name: str) -> str:
    """'Rigas Kauss 2024 I (GrDiv)' -> 'Rigas Kauss 2024'; 'Rigas Kauss I Qualification' -> 'Rigas Kauss'."""
    name = re.sub(r"\s+(I{1,3}|IV)\b.*$", "", name)
    name = re.sub(r"\s+(Qualification|Kvalifikācija|Main|\(top ?\d+\)|\(GrDiv\)|Groups)\b.*$", "", name, flags=re.I)
    return name.strip()


def stage_part(part: str) -> str:
    """'II (top72)' -> 'Top 72', 'Kvalifikācija' -> 'Qualification' (the folder's part of a multi-folder event)."""
    part = re.sub(r"^(I{1,3}|IV)\b\s*", "", part).strip() or part
    if re.fullmatch(r"groups?", part, re.I):
        return "Divisions"
    m = re.search(r"top ?(\d+)", part, re.I)
    if m:
        return f"Top {m.group(1)}"
    if re.search(r"main", part, re.I):
        return "Main"
    if re.search(r"kvalifik|qualif", part, re.I):
        return "Qualification"
    return part


def merge_multi_folder(events: list[Parsed]) -> list[Parsed]:
    """Folders that are parts of one event (same name core, dates within 2 days) become one tournament; the
    stages keep their order by date then folder (qualification -> main -> top 72)."""
    def part_rank(p: Parsed) -> int:  # qualification -> division groups -> main / top 72
        roman = re.search(r"\s(I{1,3}|IV)\b", p.name)
        if roman:
            return {"I": 0, "II": 1, "III": 2, "IV": 3}[roman.group(1)]
        name = p.name.lower()
        return 0 if re.search(r"kvalifik|qualif", name) else 2 if re.search(r"main|top ?\d+", name) else 1

    events = sorted(events, key=lambda p: (p.date, part_rank(p), p.key))
    merged: list[Parsed] = []
    for p in events:
        folder = p.key.split("/", 1)[0]
        target = next((m for m in merged if abs((date.fromisoformat(p.date) - date.fromisoformat(m.date)).days) <= 2
                       and (m.key.split("/", 1)[0] == folder
                            or (event_core(m.name) and event_core(m.name) == event_core(p.name)))), None)
        if target is None:
            p.name = base_name(p.name)
            merged.append(p)
            continue
        offset = max([g.stage_seq for g in target.games] + [3 + getattr(grp, "seq_offset", 0)
                                                             for _, grp in target.pending_groups])
        part = stage_part(p.name.replace(target.name, "").strip(" -") or folder)
        for g in p.games:
            g.stage = f"Playoff {part} {g.stage[len('Playoff '):]}" if g.stage.startswith("Playoff ") \
                else f"{part} {g.stage}"
            g.stage_seq += offset
        target.games.extend(p.games)
        for url, grp in p.pending_groups:
            grp.name = f"{part} {grp.name}".strip()
            grp.seq_offset = offset
            target.pending_groups.append((url, grp))
        for name, ref in p.players.items():
            target.players.setdefault(name, ref)
        target.extra_keys = getattr(target, "extra_keys", []) + [p.key]
    return merged


def _sportscorpion_latvia(ctx: RunContext, skips: SkipCounter) -> list[tuple[str, str]]:
    try:
        df = sportscorpion_tournaments(ctx.client, "Latvia")
    except Exception as exc:  # noqa: BLE001
        log.error("Sportscorpion tournament list not available (%s); overlap check off", exc)
        skips.skip("Sportscorpion overlap check unavailable")
        return []
    return [(r.Name, r.Date) for r in df.itertuples() if r.Date]


def _write_sheets(sheets: dict[str, set[str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["sheet_url", "linked_from"])
        for url in sorted(sheets):
            w.writerow([url, " ".join(sorted(sheets[url]))])


# --------------------------------------------------------------------------------------------------
# Ids and rows
# --------------------------------------------------------------------------------------------------


class Resolver:
    def __init__(self, mapper: PlayerMapper, registry: IdRegistry, clubs: dict[str, str]):
        self.mapper, self.registry, self.clubs = mapper, registry, clubs

    def resolve(self, name: str) -> int:
        display = sw.display_name(name)
        key = f"{fold(name)}|{fold(self.clubs.get(name, ''))}"
        ithf = self.mapper.match_ranking(display, prefer_nation="LAT", source_key=key)
        sc = None if ithf else self.mapper.match_sportscorpion(display, source_key=key)
        local = self.registry.get(key, name=name)
        return self.mapper.resolve(key, ithf=ithf, local_id=local, sc_player_id=sc, name=display)


def to_rows(events: list[Parsed], resolver: Resolver, t_reg: IdRegistry, s_reg: IdRegistry) -> list[dict]:
    """Rows for every game. Rebuilt while the "played each other" guard refuses name-based ids."""
    for _ in range(5):
        rows = _to_rows(events, resolver, t_reg, s_reg)
        if not resolver.mapper.apply_guard():
            break
    return rows


def _to_rows(events: list[Parsed], resolver: Resolver, t_reg: IdRegistry, s_reg: IdRegistry) -> list[dict]:
    rows = []
    for t in events:
        tid = t_reg.get(t.url, name=t.name)
        resolver.mapper.begin_tournament(tid)
        ids: dict[str, int] = {}
        for g in t.games:
            for n in (g.p1, g.p2):
                if n not in ids:
                    ids[n] = resolver.resolve(n)
            resolver.mapper.played(ids[g.p1], ids[g.p2])
            if ids[g.p1] == ids[g.p2]:
                continue
            stage_key = f"{t.url}#{g.stage}"
            rows.append({
                "StageID": s_reg.get(stage_key, name=g.stage), "Player1": sw.display_name(g.p1),
                "Player1ID": ids[g.p1], "Player2": sw.display_name(g.p2), "Player2ID": ids[g.p2],
                "GoalsPlayer1": g.g1, "GoalsPlayer2": g.g2, "Overtime": "Yes" if g.overtime else "No",
                "Stage": g.stage, "RoundNumber": g.round,
                "PlayoffGameNumber": g.game_no if g.stage_type == "playoff" else None, "Date": t.date,
                "TournamentName": t.name, "TournamentID": tid, "StageSequence": g.stage_seq,
                "StageType": g.stage_type, "TournamentURL": t.url, "ResultURL": g.url, "StageURL": g.url,
                "SourceURL": g.url, "Source": SOURCE, "SourceTournamentID": t.key, "SourceStageID": stage_key,
                "SourceMatchID": g.match_id,
            })
    # Old pages print Latvian names in a lossy code page ('Kalninš'); one spelling per player id, the most used.
    spellings: dict[int, Counter] = defaultdict(Counter)
    for r in rows:
        spellings[r["Player1ID"]][r["Player1"]] += 1
        spellings[r["Player2ID"]][r["Player2"]] += 1
    best = {pid: max(c.items(), key=lambda kv: (kv[1], kv[0]))[0] for pid, c in spellings.items()}
    for r in rows:
        r["Player1"], r["Player2"] = best[r["Player1ID"]], best[r["Player2ID"]]
    return rows


def run(ctx: RunContext) -> pd.DataFrame:
    sdir = ctx.source_dir("galdahokejs")
    skips = SkipCounter()
    events = crawl(ctx, skips)
    t_reg = IdRegistry(sdir / "tournament_ids.csv", TOURNAMENT_BASE + 1, ("name",))
    s_reg = IdRegistry(sdir / "stage_ids.csv", STAGE_BASE + 1, ("name",))
    p_reg = IdRegistry(sdir / "player_ids.csv", LOCAL_BASE + 1, ("name",))
    mapper = PlayerMapper(ctx.ref, "galdahokejs")
    clubs = {}
    for t in events:
        for n, ref in t.players.items():
            if getattr(ref, "club", None):
                clubs.setdefault(n, ref.club)
    df = to_frame(to_rows(events, Resolver(mapper, p_reg, clubs), t_reg, s_reg))
    write_parquet(df, ctx.data_dir / OUTPUT)
    for reg in (t_reg, s_reg, p_reg):
        reg.save()
    mapper.write_name_matches(sdir / "name_matches.csv")
    print_report(SOURCE, df, skips, mapper.stats())
    return df

