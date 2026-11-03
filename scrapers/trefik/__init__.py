"""Scraper for stiga.trefik.cz: Czech Cup rounds, Czech championships and the Czech Open, 2000-.

    python -m scrapers.trefik [--offline] [--refresh-days N]

Flow: the federation's season index (stolni-hokej.cz/pohar.html) lists every tournament -> each tournament's
main page, groups page, play-off/placement page(s) and, for international events, the participants list are
fetched once into data/trefik/raw/ (gzip) -> parsed with the shared Trefik SW parser -> one row per game.
2026 events use a newer JSON format (``<tour>/m-<src>.json``) that already carries Trefik and ITHF player ids.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import parse_qs, urljoin, urlsplit

import pandas as pd

from ..common import trefik_sw as sw
from ..common.context import RunContext
from ..common.players import PlayerMapper, fold, name_key  # noqa: F401 (PlayerMapper re-exported for tests)
from ..common.registry import IdRegistry
from ..common.report import SkipCounter, print_report
from ..common.schema import to_frame, write_parquet
from .crawl import Fetcher, list_tournaments, start_page
from .discover import Listed

log = logging.getLogger(__name__)

SOURCE = "stiga.trefik.cz"
OUTPUT = "trefik_results.parquet"
TOURNAMENT_BASE = 3_000_000_000
STAGE_BASE = 3_100_000_000
IDPL_BASE = 20_000_000
LOCAL_BASE = 21_000_000
REFRESH_DAYS = 10  # events newer than this are re-fetched every run (results may still be added)

NATION_CODES = {
    "latvia": "LAT", "czech republic": "CZE", "czechia": "CZE", "slovakia": "SVK", "slovenia": "SLO",
    "sweden": "SWE", "finland": "FIN", "norway": "NOR", "germany": "GER", "austria": "AUT", "hungary": "HUN",
    "ukraine": "UKR", "russia": "RUS", "estonia": "EST", "lithuania": "LTU", "switzerland": "SUI",
    "denmark": "DEN", "poland": "POL", "belarus": "BLR", "kazakhstan": "KAZ", "usa": "USA", "france": "FRA",
}
CATEGORY_NAMES = {"": "", "Veterans": " Veterans", "Juniors": " Juniors", "Women": " Women", "55+": " 55+",
                  "50+": " 50+", "U13": " U13", "Juniors + Women": " Juniors + Women"}


# --------------------------------------------------------------------------------------------------
# Parsed tournament (source-neutral, before ids)
# --------------------------------------------------------------------------------------------------


@dataclass
class PlayerRef:
    name: str                 # as on the page, surname first ("Plešák Pavel" / "Plešák, Pavel")
    idpl: int | None = None
    ithf: int | None = None
    nation: str | None = None
    club: str | None = None


@dataclass
class Game:
    stage: str
    stage_type: str           # roundrobin / playoff
    stage_seq: int
    round: int | None
    game_no: int | None
    p1: str
    p2: str
    g1: int
    g2: int
    overtime: bool
    match_id: str
    url: str


@dataclass
class Parsed:
    key: str
    name: str
    date: str
    url: str
    players: dict[str, PlayerRef] = field(default_factory=dict)  # by page name
    games: list[Game] = field(default_factory=list)
    pending_groups: list = field(default_factory=list)  # (url, trefik_sw.Group) until names are resolved


def tournament_name(item: Listed, title: str, when: date) -> str:
    label = item.label
    if item.category is not None:
        cat = CATEGORY_NAMES.get(item.category, f" {item.category}").strip()
        return f"Czech Championship {when.year}" + (f" – {cat}" if cat else "")
    if "czech open" in sw.ascii_fold(label):
        return f"Czech Open {when.year}"
    place = title.split(",", 1)[0].strip() if title else label
    if not place or parse_date_only(place):
        place = label
    if sw.ascii_fold(place).startswith("moravia open") or label.endswith(", MO"):
        return f"Moravia Open {when.year}"
    return f"Czech Cup {place} {when.year}"


def parse_date_only(text: str) -> bool:
    return bool(re.fullmatch(r"[\d.\s-]+", text))


# --------------------------------------------------------------------------------------------------
# HTML tournaments
# --------------------------------------------------------------------------------------------------


def parse_html_event(fetcher: Fetcher, item: Listed, skips: SkipCounter, refresh: bool) -> list[Parsed]:
    start = start_page(fetcher, item, refresh=refresh)
    if start is None:
        skips.skip("tournament page missing (404)", item.key)
        return []
    url, html = start
    refresh_match = re.search(r'http-equiv="refresh"[^>]*url=([^"\']+)', html, re.I)
    if refresh_match and len(html) < 1000:
        url = urljoin(url, refresh_match.group(1).strip())
        html = fetcher.text(url, refresh=refresh) or ""
    ev = sw.parse_event_page(html, url)
    has_cross = 'class="kx"' in html or "class=kx" in html
    hub = [] if (ev.groups_url or ev.playoff_urls or ev.final_table or has_cross) else sw.hub_links(html, url)
    if not hub:
        p = _parse_one(fetcher, item, item.key, item.category, url, html, skips, refresh)
        return [p] if p else []
    out = []
    for cat, sub_url in hub:
        sub_key = f"{item.key}/{sub_url.rsplit('/', 1)[1].rsplit('.', 1)[0].lower()}"
        if cat == "Teams":
            skips.skip("team championship (not individual games)", sub_key)
            continue
        sub_html = fetcher.text(sub_url, refresh=refresh)
        if not sub_html:
            skips.skip("category page missing (404)", sub_key)
            continue
        p = _parse_one(fetcher, item, sub_key, cat, sub_url, sub_html, skips, refresh)
        if p:
            out.append(p)
    return out


def _parse_one(fetcher: Fetcher, item: Listed, key: str, category: str | None, url: str, html: str,
               skips: SkipCounter, refresh: bool) -> Parsed | None:
    pages = sw.collect_pages(url, html, lambda u: fetcher.text(u, refresh=refresh))
    ev = sw.parse_event_page(html, url)
    when = ev.date
    if when is None:
        when = next((d for d in (sw.parse_date_text(sw.parse_event_page(h, u).title) for u, h in pages.items())
                     if d), None) or sw.parse_date_text(item.index_date)
    if when is None:
        skips.skip("tournament without a date", key)
        return None
    named = Listed(item.key, item.url, item.season, item.label, item.row_label, item.index_date, category, item.kind)
    parsed = Parsed(key, tournament_name(named, ev.title, when), when.isoformat(), url)
    return assemble(parsed, pages, skips)


def assemble(parsed: Parsed, pages: dict[str, str], skips: SkipCounter) -> Parsed:
    """Read players, cross-tables and play-off series from every result page of one event (any Trefik SW
    export: stiga.trefik.cz or galdahokejs.lv). Group games are added later by ``resolve_groups``."""
    key = parsed.key
    groups: list[tuple[str, sw.Group]] = []
    seen_groups: set[tuple] = set()
    series_all: list[tuple[str, sw.Series]] = []
    seen_series: set[tuple] = set()
    for page_url, page in pages.items():
        page_ev = sw.parse_event_page(page, page_url)
        for row in page_ev.final_table:
            ref = parsed.players.setdefault(row.name, PlayerRef(row.name))
            ref.idpl = ref.idpl or row.idpl
            ref.nation = ref.nation or NATION_CODES.get((row.nation or "").lower())
            ref.club = ref.club or (row.club if row.club and not row.nation else None)
        for idpl, ithf, name in sw.parse_participants(page):
            ref = next((p for p in parsed.players.values() if idpl and p.idpl == idpl), None) \
                or parsed.players.get(sw.clean_name(name))
            if ref is None and name:
                ref = parsed.players.setdefault(sw.clean_name(name), PlayerRef(sw.clean_name(name), idpl))
            if ref is not None:
                ref.idpl = ref.idpl or idpl
                ref.ithf = ref.ithf or ithf
        for g in sw.parse_groups_page(page):
            sig = sw.group_signature(g)
            if sig in seen_groups:
                known = next(x for _, x in groups if sw.group_signature(x) == sig)
                if known.phase is None and g.phase is not None:
                    known.phase = g.phase
                continue
            if sig not in seen_groups:
                seen_groups.add(sig)
                base, n = g.name, 2
                while any(x.phase == g.phase and x.name == g.name for _, x in groups):
                    g.name = f"{base}#{n}"
                    n += 1
                groups.append((page_url, g))
        for s in sw.parse_playoff_page(page):
            sig = (s.label, s.player1, s.player2, tuple(s.games))
            if sig not in seen_series:
                seen_series.add(sig)
                series_all.append((page_url, s))
    # the same person can be printed "Petr Patrik" (final table) and "Patrik Petr" (play-off page): keep the
    # first spelling seen (main page first) and map the others to it
    canon: dict[frozenset, str] = {}
    for n in list(parsed.players):
        canon.setdefault(_pkey(n), n)
    for _, s in series_all:
        s.player1 = canon.setdefault(_pkey(s.player1), s.player1)
        s.player2 = canon.setdefault(_pkey(s.player2), s.player2)
        for n, idpl in ((s.player1, s.idpl1), (s.player2, s.idpl2)):
            ref = parsed.players.setdefault(n, PlayerRef(n))
            ref.idpl = ref.idpl or idpl
    for _, g in groups:
        if g.phase is None:  # no heading on the page: a group with carried-over ("K") results is a final group
            g.phase = "final" if any(re.search(r"\bK\b", c) for r in g.rows for c in r.cells) else "basic"
    if not groups:
        skips.skip("no group results", key)
    parsed.pending_groups = groups
    _playoff_games(parsed, series_all, skips)
    return parsed


def resolve_groups(parsed: Parsed, pool: dict[int, list[str]], skips: SkipCounter,
                   reference: list[str] | None = None) -> None:
    """Turn the cross-tables into games, resolving short labels to full names. Candidates are the event's own
    names first, then (for pages without any full-name list) every name seen on the site in nearby seasons, then
    the optional `reference` names (e.g. a nation's players in ranking.txt, as 'Surname First')."""
    local = _unique_names(parsed.players)
    year = int(parsed.date[:4])
    groups = [g for _, g in parsed.pending_groups]
    sw.resolve_all_groups(groups, local)
    if any(not r.full for g in groups for r in g.rows):
        fallback = _unique_names(n for y in range(year - 3, year + 4) for n in pool.get(y, []))
        sw.resolve_all_groups(groups, fallback)
    if reference and any(not r.full for g in groups for r in g.rows):
        sw.resolve_all_groups(groups, _unique_names(reference))
    for url, g in parsed.pending_groups:
        for row in g.rows:
            if row.full:
                parsed.players.setdefault(row.full, PlayerRef(row.full))
            else:
                skips.skip("cross-table name not resolved", f"{parsed.key} {g.name}: {row.label}")
        _group_games(parsed, g, url, skips)
    parsed.pending_groups = []


def _unique_names(names) -> list[str]:
    seen: dict[frozenset, str] = {}
    for n in names:
        seen.setdefault(_pkey(n), n)
    return sorted(seen.values())


def _group_games(parsed: Parsed, g: sw.Group, url: str, skips: SkipCounter) -> None:
    rounds = sw.round_lookup(g)
    stage = (("Basic groups " if g.phase == "basic" else "Final groups ") + g.name).strip()
    seq = (1 if g.phase == "basic" else 2) + getattr(g, "seq_offset", 0)
    for i, row in enumerate(g.rows):
        for j in range(i + 1, len(g.rows)):
            cell = row.cells[j] if j < len(row.cells) else ""
            scores = sw.parse_cell_scores(cell)
            if not scores:
                if cell.strip(" \xa0*-"):
                    skips.skip("group cell without a score", f"{parsed.key} {g.name}: {cell!r}")
                else:
                    skips.skip("unplayed group game")
                continue
            other = g.rows[j]
            if not row.full or not other.full:
                skips.skip("game with an unresolved player", f"{parsed.key} {g.name}")
                continue
            rnd = rounds.get(frozenset((row.full, other.full)))
            for k, (g1, g2, flag) in enumerate(scores, start=1):
                if flag == "K":
                    skips.skip("result carried forward / forfeit (K)")
                    continue
                parsed.games.append(Game(stage, "roundrobin", seq, rnd, None, row.full, other.full, g1, g2,
                                         flag == "P", f"{parsed.key}/{g.phase}/{g.name}/{i + 1}-{j + 1}/{k}", url))


def playoff_stage(brackets: dict[str, set[int]], order: list[str], bracket: str, size: int) -> tuple[str, int]:
    """Stage label and sequence for one play-off round: main bracket first (earliest round first), then B, C..."""
    seq = 3
    for b in order:
        for s in sorted(brackets[b], reverse=True):
            if b == bracket and s == size:
                if s == 1 and re.search(r"m[ií]sto|place|\d+(st|nd|rd|th)\b", b, re.I):
                    return f"Playoff {b}", seq  # placement match, e.g. "O 11. místo"
                label = "Final" if s == 1 else f"1/{s}"
                return "Playoff " + (f"{b} " if b else "") + label, seq
            seq += 1
    raise KeyError(bracket)


def _playoff_games(parsed: Parsed, series_all, skips: SkipCounter) -> None:
    brackets: dict[str, set[int]] = defaultdict(set)
    for _, s in series_all:
        b, size = sw.split_bracket(s.label)
        brackets[b].add(size)
    order = sorted(brackets)  # "" (main) first, then B, C, ...
    seen_series: set[tuple] = set()
    for url, s in series_all:
        b, size = sw.split_bracket(s.label)
        rnd = sorted(brackets[b], reverse=True).index(size) + 1
        stage, seq = playoff_stage(brackets, order, b, size)
        sid = (s.label, s.player1, s.player2)
        n_dup = sum(1 for x in seen_series if x[:3] == sid)
        seen_series.add((*sid, n_dup))
        if not s.games:
            reason = "play-off walkover (K)" if s.walkover else "series without game scores"
            skips.skip(reason, f"{parsed.key} {s.label}: {s.player1} - {s.player2}")
            continue
        for n, (g1, g2, ot) in enumerate(s.games, start=1):
            mid = f"{parsed.key}/po/{s.label}/{fold(s.player1)}-{fold(s.player2)}" + (f"#{n_dup}" if n_dup else "")
            parsed.games.append(Game(stage, "playoff", seq, rnd, n, s.player1, s.player2, g1, g2,
                                     ot, f"{mid}/{n}", url))


# --------------------------------------------------------------------------------------------------
# JSON tournaments (2026-)
# --------------------------------------------------------------------------------------------------


def parse_json_event(fetcher: Fetcher, item: Listed, skips: SkipCounter, refresh: bool) -> Parsed | None:
    q = parse_qs(urlsplit(item.url).query)
    tour, src = q.get("tour", [""])[0], q.get("src", [""])[0]
    data_url = urljoin(item.url, f"{tour}/m-{src}.json")
    raw = fetcher.get(data_url, refresh=refresh)
    if not raw:
        skips.skip("tournament data missing (404)", item.key)
        return None
    data = json.loads(raw.decode("utf-8-sig"))
    when = sw.parse_date_text(data.get("tourn", {}).get("date", "")) or sw.parse_date_text(item.index_date)
    if when is None:
        skips.skip("tournament without a date", item.key)
        return None
    title = data.get("tourn", {}).get("where", item.label)
    parsed = Parsed(item.key, tournament_name(item, title, when), when.isoformat(), item.url)
    by_id: dict[int, str] = {}
    for p in data.get("players", []):
        name = p["name"]
        by_id[p["id"]] = name
        parsed.players[name] = PlayerRef(name, p["id"], p.get("wr_id") or None)
    groups = {g["id"]: g["name"] for g in data.get("groups", [])}
    for m in data.get("matches", []):
        gid = m["gr"]
        if gid >= 1000:
            continue  # play-off series shown as groups; the games are in "play-off"
        stage = ("Basic groups " if gid < 100 else "Final groups ") + groups.get(gid, str(gid))
        scores = sw.parse_cell_scores(m.get("res") or "")
        p1, p2 = by_id.get(m["h_id"]), by_id.get(m["a_id"])
        if not scores or not p1 or not p2:
            skips.skip("unplayed group game" if not scores else "game with an unknown player")
            continue
        for k, (g1, g2, flag) in enumerate(scores, start=1):
            if flag == "K":
                skips.skip("result carried forward from basic group")
                continue
            parsed.games.append(Game(stage, "roundrobin", 1 if gid < 100 else 2, m.get("rnd"), None, p1, p2, g1, g2,
                                     flag == "P", f"{item.key}/g{gid}/r{m.get('rnd')}/{m['h_id']}-{m['a_id']}/{k}",
                                     item.url))
    brackets: dict[str, set[int]] = defaultdict(set)
    for m in data.get("play-off", []):
        b, size = sw.split_bracket(m["po"])
        brackets[b].add(size)
    order = sorted(brackets)
    for m in data.get("play-off", []):
        b, size = sw.split_bracket(m["po"])
        scores = sw.parse_cell_scores(m.get("res") or "")
        p1, p2 = by_id.get(m["h_id"]), by_id.get(m["a_id"])
        if not scores or not p1 or not p2:
            skips.skip("unplayed play-off game")
            continue
        g1, g2, _ = scores[0]
        stage, seq = playoff_stage(brackets, order, b, size)
        parsed.games.append(Game(stage, "playoff", seq, sorted(brackets[b], reverse=True).index(size) + 1, m["m_ord"], p1, p2, g1, g2,
                                 bool(m.get("ot")), f"{item.key}/po{m['po_id']}/{m['m_ord']}", item.url))
    return parsed


# --------------------------------------------------------------------------------------------------
# Ids and rows
# --------------------------------------------------------------------------------------------------


def _pkey(name: str) -> frozenset:
    return name_key(name.replace(",", " "))


class IdResolver:
    """Trefik idpl / ITHF id / local id for every player name, using every tournament seen in this run."""

    def __init__(self, parsed: list[Parsed], mapper: PlayerMapper, registry: IdRegistry):
        self.mapper = mapper
        self.registry = registry
        self.name_to_idpl: dict[frozenset, set[int]] = defaultdict(set)
        self.idpl_to_ithf: dict[int, int] = {}
        self.idpl_name: dict[int, str] = {}
        for t in parsed:
            for ref in t.players.values():
                if ref.idpl:
                    self.name_to_idpl[_pkey(ref.name)].add(ref.idpl)
                    self.idpl_name.setdefault(ref.idpl, ref.name)
                    if ref.ithf:
                        self.idpl_to_ithf[ref.idpl] = ref.ithf

    def resolve(self, ref: PlayerRef) -> int:
        idpl = ref.idpl
        if idpl is None:
            cands = self.name_to_idpl.get(_pkey(ref.name), set())
            idpl = next(iter(cands)) if len(cands) == 1 else None
        ithf = ref.ithf or (self.idpl_to_ithf.get(idpl) if idpl else None)
        source_key = f"idpl:{idpl}" if idpl else f"name:{fold(ref.name)}"
        if ithf is None:
            ithf = self.mapper.match_ranking(sw.display_name(ref.name), nation=ref.nation, prefer_nation="CZE",
                                             source_key=source_key)
        local = IDPL_BASE + idpl if idpl else self.registry.get(fold(ref.name), name=ref.name)
        return self.mapper.resolve(source_key, ithf=ithf, local_id=local)


def to_rows(parsed: list[Parsed], resolver: IdResolver, t_reg: IdRegistry, s_reg: IdRegistry) -> list[dict]:
    rows = []
    for t in parsed:
        tid = t_reg.get(t.key, name=t.name)
        ids: dict[str, int] = {}
        for g in t.games:
            for n in (g.p1, g.p2):
                if n not in ids:
                    ids[n] = resolver.resolve(t.players.get(n) or PlayerRef(n))
            stage_key = f"{t.key}#{g.stage}"
            sid = s_reg.get(stage_key, name=g.stage)
            if ids[g.p1] == ids[g.p2]:
                continue
            rows.append({
                "StageID": sid, "Player1": sw.display_name(g.p1), "Player1ID": ids[g.p1],
                "Player2": sw.display_name(g.p2), "Player2ID": ids[g.p2], "GoalsPlayer1": g.g1,
                "GoalsPlayer2": g.g2, "Overtime": "Yes" if g.overtime else "No", "Stage": g.stage,
                "RoundNumber": g.round, "PlayoffGameNumber": g.game_no if g.stage_type == "playoff" else None,
                "Date": t.date, "TournamentName": t.name, "TournamentID": tid, "StageSequence": g.stage_seq,
                "StageType": g.stage_type, "TournamentURL": t.url, "ResultURL": g.url, "StageURL": g.url,
                "SourceURL": g.url, "Source": SOURCE, "SourceTournamentID": t.key, "SourceStageID": stage_key,
                "SourceMatchID": g.match_id,
            })
    return rows


# --------------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------------


def crawl(ctx: RunContext, skips: SkipCounter, refresh_days: int = REFRESH_DAYS) -> list[Parsed]:
    sdir = ctx.source_dir("trefik")
    fetcher = Fetcher(ctx.client, sdir / "raw", offline=ctx.offline)
    listed = list_tournaments(fetcher, refresh_index=not ctx.offline)
    by_season = defaultdict(int)
    parsed: list[Parsed] = []
    today = date.today()
    for item in listed:
        if item.is_team_event:
            skips.skip("team championship (not individual games)", item.key)
            continue
        idx_date = sw.parse_date_text(item.index_date)
        refresh = idx_date is not None and today - idx_date < timedelta(days=refresh_days)
        try:
            if item.kind == "json":
                found = [p for p in [parse_json_event(fetcher, item, skips, refresh)] if p]
            else:
                found = parse_html_event(fetcher, item, skips, refresh)
        except Exception:  # noqa: BLE001 - one broken page must not stop the run
            log.exception("%s failed", item.key)
            skips.skip("tournament failed to parse", item.key)
            continue
        parsed.extend(found)
        by_season[item.season] += len(found)
    log.info("fetched %d new pages", fetcher.fetched)
    pool: dict[int, list[str]] = defaultdict(list)
    for p in parsed:
        pool[int(p.date[:4])].extend(n for n in p.players if " " in n and "," not in n)
    kept = []
    for p in parsed:
        resolve_groups(p, pool, skips)
        if p.games:
            kept.append(p)
        else:
            skips.skip("tournament without games", p.key)
    parsed = kept
    print("Tournaments per season:", ", ".join(f"{s}: {n}" for s, n in sorted(by_season.items())))
    return parsed


def run(ctx: RunContext) -> pd.DataFrame:
    sdir = ctx.source_dir("trefik")
    skips = SkipCounter()
    parsed = crawl(ctx, skips, ctx.extra.get("refresh_days", REFRESH_DAYS))
    t_reg = IdRegistry(sdir / "tournament_ids.csv", TOURNAMENT_BASE + 1, ("name",))
    s_reg = IdRegistry(sdir / "stage_ids.csv", STAGE_BASE + 1, ("name",))
    p_reg = IdRegistry(sdir / "player_ids.csv", LOCAL_BASE + 1, ("name",))
    mapper = PlayerMapper(ctx.ref, "trefik")
    resolver = IdResolver(parsed, mapper, p_reg)
    df = to_frame(to_rows(parsed, resolver, t_reg, s_reg))
    write_parquet(df, ctx.data_dir / OUTPUT)
    for reg in (t_reg, s_reg, p_reg):
        reg.save()
    mapper.write_name_matches(sdir / "name_matches.csv")
    print_report(SOURCE, df, skips, mapper.stats())
    return df
