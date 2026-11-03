"""Scraper for escore.live (Laravel + Inertia): table hockey events from 2025-12-01 (Latvia, Ukraine Cup, ...).

    python -m scrapers.escore [--offline]

Every public page embeds its data as JSON in <div id="app" data-page="...">. Events have sequential ids:
``/events/<id>/particiants`` (sic) gives the event, its sport and its result tabs; each ``/events/<id>/net/<net>``
tab gives the games, groups and elimination trees. Only the props we use are cached (data/escore/raw/), because
each page also embeds ~2.5 MB of UI translations. ``/api`` is disallowed by robots.txt and not used.
"""

from __future__ import annotations

import gzip
import html as htmllib
import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from ..common.context import RunContext
from ..common.dedupe import similarity
from ..common.trefik_sw import ascii_fold
from ..common.http import AccessDenied
from ..common.overlaps import near_date, table_hockey_eu_tournaments
from ..common.players import PlayerMapper
from ..common.registry import IdRegistry
from ..common.report import SkipCounter, print_report
from ..common.schema import to_frame, write_parquet

log = logging.getLogger(__name__)

SOURCE = "escore.live"
OUTPUT = "escore_results.parquet"
BASE = "https://escore.live"
TOURNAMENT_BASE = 5_000_000_000
STAGE_BASE = 5_100_000_000
LOCAL_BASE = 40_000_000
FIRST_DATE = date(2025, 12, 1)   # galdahokejs.lv owns Latvian events before this date
MISS_RUN = 25                    # stop probing new ids after this many consecutive missing events
REFRESH_DAYS = 10
KEEP_PROPS = ("competitionEvent", "participants", "tabs", "otherEvents", "games", "groups", "eliminationTrees",
              "net")


# --------------------------------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------------------------------


def page_props(html: str) -> dict | None:
    m = re.search(r'<div id="app" data-page="([^"]*)"', html)
    if not m:
        return None
    data = json.loads(htmllib.unescape(m.group(1)))
    return {k: v for k, v in data.get("props", {}).items() if k in KEEP_PROPS}


class Store:
    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.raw = ctx.source_dir("escore") / "raw"

    def path(self, event_id: int, net_id: int | None = None) -> Path:
        name = f"{event_id}.json.gz" if net_id is None else f"{event_id}_net{net_id}.json.gz"
        return self.raw / name

    def get(self, url: str, path: Path, refresh: bool = False) -> dict | None:
        """Props of a page, cached; ``{}`` for a missing page (cached as an empty file)."""
        if path.exists() and not (refresh and not self.ctx.offline):
            body = path.read_bytes()
            return json.loads(gzip.decompress(body)) if body else {}
        if self.ctx.offline:
            return None
        try:
            resp = self.ctx.client.get(url)
        except AccessDenied:  # a private event: treated as missing, never worked around
            resp = None
        if resp is None or resp.status_code == 404:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
            return {}
        resp.raise_for_status()
        props = page_props(resp.content.decode("utf-8", errors="replace")) or {}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(json.dumps(props, ensure_ascii=False, sort_keys=True).encode(), mtime=0))
        return props

    def event(self, event_id: int, refresh: bool = False) -> dict | None:
        return self.get(f"{BASE}/events/{event_id}/particiants", self.path(event_id), refresh)

    def net(self, event_id: int, net_id: int, refresh: bool = False) -> dict | None:
        return self.get(f"{BASE}/events/{event_id}/net/{net_id}", self.path(event_id, net_id), refresh)


def sport_of(props: dict, event_id: int) -> str | None:
    for e in props.get("otherEvents") or []:
        if e.get("id") == event_id:
            return e.get("sports_type")
    return None


def discover(store: Store, skips: SkipCounter) -> list[int]:
    """Probe event ids 1, 2, ... (cached ones are not re-fetched) until MISS_RUN consecutive misses past the
    last existing id. Returns the table hockey event ids."""
    found, misses, eid = [], 0, 0
    last = max((int(p.name.split(".")[0]) for p in store.raw.glob("*.json.gz")
                if "_net" not in p.name and p.stat().st_size), default=0)
    while misses < MISS_RUN:
        eid += 1
        # Ids after the newest known event were "missing" last time: probe them again, new events land there.
        props = store.event(eid, refresh=eid > last)
        if props is None:  # offline and never fetched
            misses += 1
            continue
        if not props:
            misses += 1
            continue
        misses = 0
        if sport_of(props, eid) == "table_hockey":
            found.append(eid)
        else:
            skips.skip("not table hockey")
    return found


# --------------------------------------------------------------------------------------------------
# Transform
# --------------------------------------------------------------------------------------------------


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def event_name(ev: dict, others: list[dict] | None = None) -> str:
    """Competition name ('Latvijas čempionāts 2026'), plus the event name ('Pro', 'Amatieri') when the competition
    has more than one singles event; the year is added when neither name has one."""
    comp = " ".join(str((ev.get("competition") or {}).get("name") or "").split())
    own = " ".join(str(ev.get("name", "")).split())
    singles = [o for o in others or [] if o.get("type") == "singles"]
    if not comp:
        name = own
    elif len(singles) > 1 and fold_name(own) not in fold_name(comp):
        name = f"{comp} – {own}"
    else:
        name = comp
    year = str(ev.get("start_date", ""))[:4]
    if year and not re.search(r"\b(19|20)\d\d\b", name):
        name = f"{name} {year}"
    return name


def fold_name(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_fold(text).lower()).split())


def _custom(obj: dict) -> str | None:
    return obj.get("custom_name") if obj.get("use_custom_name") and obj.get("custom_name") else None


def _prefix(label: str | None) -> str:
    """Tab/net label without the generic words: '1. līga Play-off' -> '1. līga', 'Groups' -> ''."""
    label = re.sub(r"\b(play-?off|PO)\b", " ", label or "", flags=re.I)
    label = re.sub(r"^\s*(groups?|grupas?)\b", "", label, flags=re.I)
    return " ".join(label.split())


def round_label(size: int, rnd: int) -> str:
    """Bracket of `size` players, round 1-based -> '1/8', '1/4', '1/2', 'Final'."""
    full = 1
    while full < size:
        full *= 2
    left = full >> (rnd - 1)
    return "Final" if left <= 2 else f"1/{left // 2}"


def stages_of(event_id: int, nets: list[dict]) -> dict[tuple, dict]:
    """(kind, id) -> {name, seq, type, ...} for every group and elimination tree, in net order. Group phases are
    'Basic groups' (first net with groups) and 'Final groups' (later ones); trees get one stage per round
    (see tree_stage)."""
    out: dict[tuple, dict] = {}
    seq = 0
    group_nets = 0
    for props in sorted(nets, key=lambda p: ((p.get("net") or {}).get("order") or 0, (p.get("net") or {}).get("id"))):
        net = props.get("net") or {}
        label = _prefix(_custom(net) or net.get("_label"))
        offset = 0  # a tab named '9.-16. Place' holds trees numbered 1.-8.: shift them to the real places
        m = re.match(r"^(\d+)\.\s*-\s*(\d+)\.\s*Place\b\s*(.*)$", label, re.I)
        if m:
            offset = int(m.group(1)) - 1
            label = m.group(3).strip() or f"{m.group(1)}.-{m.group(2)}. place"
        groups = sorted((g["group"] for g in props.get("groups") or []), key=lambda g: (g.get("order") or 0, g["id"]))
        if groups:
            phase = "Basic groups" if group_nets == 0 else "Final groups"
            group_nets += 1
        for g in groups:
            seq += 1
            gname = _custom(g) or (str(g.get("group_number", "")) if len(groups) > 1 else "")
            parts = [label] if label and (not gname or fold_name(label) not in fold_name(gname)) else []
            name = " ".join([phase, *parts, gname]).strip()
            n = 2
            while any(v.get("name") == name for v in out.values()):  # two tabs with the same label
                name = f"{' '.join([phase, *parts, gname]).strip()} #{n}"
                n += 1
            out[("group", g["id"])] = {"name": name, "seq": seq, "type": "roundrobin", "key": f"g{g['id']}"}
        trees = sorted((t["elimination_tree"] for t in props.get("eliminationTrees") or []),
                       key=lambda t: (t.get("order") or 0, t["id"]))
        for t in trees:
            start, end = _int(t.get("start_place")) or 1, _int(t.get("end_place")) or 2
            size = max(2, end - start + 1)
            rounds = max(1, (size - 1).bit_length())
            tname = _custom(t)
            prefix = " ".join(x for x in (re.sub(r"^\d+\.-\d+\. place$", "", label), tname) if x)
            out[("tree", t["id"])] = {"prefix": prefix, "start": start + offset, "end": end + offset,
                                      "size": size, "seq": seq + 1, "rounds": rounds, "type": "playoff",
                                      "key": f"t{t['id']}"}
            seq += rounds
    return out


def tree_stage(tree: dict, rnd: int | None) -> dict:
    """Stage of one round of an elimination tree: 'Playoff 1. līga 1/8', 'Playoff 3.-4. place',
    'Playoff 5.-8. place 1/2'."""
    rnd = rnd or 1
    parts = ["Playoff"] + ([tree["prefix"]] if tree["prefix"] else [])
    if tree["start"] > 1:
        parts.append(f"{tree['start']}.-{tree['end']}. place")
        if tree["size"] > 2:
            parts.append(round_label(tree["size"], rnd))
    else:
        parts.append(round_label(tree["size"], rnd))
    return {"name": " ".join(parts), "seq": tree["seq"] + min(rnd, tree["rounds"]) - 1, "type": "playoff",
            "key": f"{tree['key']}r{rnd}"}


def event_games(event_id: int, ev_props: dict, nets: list[dict], skips: SkipCounter) -> list[dict]:
    """One dict per actual game (a best-of series gives one per set)."""
    ev = ev_props["competitionEvent"]
    stages = stages_of(event_id, nets)
    players = {}
    for p in ev_props.get("participants") or []:
        if p.get("player_id"):
            players[p["player_id"]] = p
    games = {}
    for props in nets:
        for g in (props.get("games") or {}).values():
            games[g["id"]] = g
    out = []
    for g in sorted(games.values(), key=lambda g: g["id"]):
        if g.get("status") != "finished":
            skips.skip(f"game status {g.get('status')}")
            continue
        p1, p2 = g.get("player1_id"), g.get("player2_id")
        if not p1 or not p2:
            skips.skip("bye")
            continue
        if p1 not in players or p2 not in players:
            skips.skip("game with an unknown player", f"{event_id}/{g['id']}")
            continue
        stage = stages.get(("group", g["group_id"])) if g.get("group_id") else \
            stages.get(("tree", g.get("elimination_tree_id")))
        if stage is not None and stage["type"] == "playoff":
            rnd0 = _int(g.get("round_nr"))
            stage = tree_stage(stage, None if rnd0 is None else rnd0 + 1)
        if stage is None:
            skips.skip("game without a stage", f"{event_id}/{g['id']}")
            continue
        try:
            sets = json.loads(g.get("set_score") or "[]")
            ots = json.loads(g.get("set_overtimes") or "null") or []
        except ValueError:
            sets, ots = [], []
        if sets:
            scores = [(_int(s[0]), _int(s[1]), bool(ots[i]) if i < len(ots) else False) for i, s in enumerate(sets)]
        else:
            scores = [(_int(g.get("player1_score")), _int(g.get("player2_score")), False)]
        if stage["type"] == "roundrobin" and len(scores) > 1:
            pass  # a group game played as several sets: still one row per set
        for n, (a, b, ot) in enumerate(scores, start=1):
            if a is None or b is None:
                skips.skip("game without a score", f"{event_id}/{g['id']}")
                continue
            rnd = _int(g.get("round_nr"))
            out.append({
                "event_id": event_id, "game_id": g["id"], "set": n, "p1": p1, "p2": p2, "g1": a, "g2": b,
                "ot": ot, "stage": stage, "round": None if rnd is None else rnd + 1,
                "game_no": n if stage["type"] == "playoff" else None, "net_id": g.get("net_id"),
                "date": str(g.get("ended_at") or ev.get("start_date"))[:10],
            })
    return out


def player_name(p: dict) -> str:
    pl = p.get("player") or {}
    return " ".join(f"{p.get('name') or pl.get('name') or ''} {p.get('surname') or pl.get('surname') or ''}".split())


class Resolver:
    def __init__(self, mapper: PlayerMapper):
        self.mapper = mapper

    def resolve(self, p: dict) -> int:
        pl = p.get("player") or {}
        pid = p["player_id"]
        key = f"escore:{pid}"
        name = player_name(p)
        nation = pl.get("country_code3")
        ithf = _int(pl.get("ithf_id"))
        if ithf is None:
            ithf = self.mapper.match_ranking(name, nation=nation, source_key=key)
        sc = None if ithf else self.mapper.match_sportscorpion(name, nation, source_key=key)
        return self.mapper.resolve(key, ithf=ithf, local_id=LOCAL_BASE + pid, sc_player_id=sc)


def crawl(ctx: RunContext, skips: SkipCounter) -> list[tuple[int, dict, list[dict]]]:
    store = Store(ctx)
    today = date.today()
    events = []
    for eid in discover(store, skips):
        props = store.event(eid)
        ev = props.get("competitionEvent") or {}
        start = ev.get("start_date")
        recent = start and today - date.fromisoformat(start[:10]) < timedelta(days=REFRESH_DAYS)
        if recent:
            props = store.event(eid, refresh=True) or props
        if ev.get("type") != "singles":
            skips.skip(f"event type {ev.get('type')} (not singles)", f"{eid} {ev.get('name')}")
            continue
        nets = []
        for tab in props.get("tabs") or []:
            if isinstance(tab.get("id"), int):
                net = store.net(eid, tab["id"], refresh=bool(recent))
                if net:
                    net.setdefault("net", {})["_label"] = tab.get("label")
                    nets.append(net)
        events.append((eid, props, nets))
    return events


def run(ctx: RunContext) -> pd.DataFrame:
    sdir = ctx.source_dir("escore")
    skips = SkipCounter()
    events = crawl(ctx, skips)
    try:
        the = table_hockey_eu_tournaments(ctx.client)
        the_list = list(zip(the["TournamentName"], the["Date"]))
    except Exception as exc:  # noqa: BLE001
        log.error("table-hockey.eu list not available (%s); overlap check off", exc)
        the_list = []
    s_reg = IdRegistry(sdir / "stage_ids.csv", STAGE_BASE + 1, ("name",))
    mapper = PlayerMapper(ctx.ref, "escore")
    resolver = Resolver(mapper)
    rows = []
    for eid, props, nets in events:
        ev = props["competitionEvent"]
        name, start = event_name(ev, props.get("otherEvents")), str(ev.get("start_date"))[:10]
        if date.fromisoformat(start) < FIRST_DATE:
            skips.skip("before 2025-12-01 (galdahokejs.lv)", f"{start} {name}")
            continue
        dup = [t for t in the_list if near_date(start, t[1]) and similarity(name, t[0]) >= 0.6]
        if dup:
            skips.skip("also on table-hockey.eu", f"{start} {name} = {dup[0][0]}")
            log.info("skip %s %s: on table-hockey.eu as %s", start, name, dup[0][0])
            continue
        players = {p["player_id"]: p for p in props.get("participants") or [] if p.get("player_id")}
        ids = {pid: resolver.resolve(p) for pid, p in players.items()}
        url = f"{BASE}/events/{eid}/particiants"
        for g in event_games(eid, props, nets, skips):
            st = g["stage"]
            stage_key = f"{eid}/{st['key']}"
            net_url = f"{BASE}/events/{eid}/net/{g['net_id']}"
            if ids[g["p1"]] == ids[g["p2"]]:
                continue
            rows.append({
                "StageID": s_reg.get(stage_key, name=st["name"]), "Player1": player_name(players[g["p1"]]),
                "Player1ID": ids[g["p1"]], "Player2": player_name(players[g["p2"]]), "Player2ID": ids[g["p2"]],
                "GoalsPlayer1": g["g1"], "GoalsPlayer2": g["g2"], "Overtime": "Yes" if g["ot"] else "No",
                "Stage": st["name"], "RoundNumber": g["round"], "PlayoffGameNumber": g["game_no"],
                "Date": start, "TournamentName": name, "TournamentID": TOURNAMENT_BASE + eid,
                "StageSequence": st["seq"], "StageType": st["type"], "TournamentURL": url, "ResultURL": net_url,
                "StageURL": net_url, "SourceURL": net_url, "Source": SOURCE, "SourceTournamentID": str(eid),
                "SourceStageID": stage_key, "SourceMatchID": f"{eid}/{g['game_id']}/{g['set']}",
            })
    df = to_frame(rows)
    write_parquet(df, ctx.data_dir / OUTPUT)
    s_reg.save()
    mapper.write_name_matches(sdir / "name_matches.csv")
    print_report(SOURCE, df, skips, mapper.stats())
    return df
