"""Scraper for tulos.poytajaakiekko.fi (Finnish ranking tournaments, 1992-).

    python -m scrapers.finland [--offline]

Status: **waiting for access.** The public JSON endpoints ``/api/events`` (event index with every sub-tournament),
``/api/events/<slug>`` and ``/api/players/search`` answer anonymous requests, but the results
(``/api/tournaments/<slug>``) only answer requests that carry the site's internal API key
(``{"error":"Invalid API access"}`` / HTTP 401 otherwise). The site's own pages send that key from their JavaScript
bundle; using it from a scraper would be getting around the access check, so this module does not. See README.md
("Finland") for the access request.

What runs now: the event index is fetched and cached, every finished sub-tournament gets its permanent
TournamentID/StageID-ready entry in data/finland/tournament_ids.csv, and one results endpoint is probed per run so the
log says when access starts working. No Parquet is written until results are available.
"""

from __future__ import annotations

import gzip
import json
import logging

import pandas as pd

from ..common.context import RunContext
from ..common.http import AccessDenied
from ..common.players import PlayerMapper, to_int
from ..common.registry import IdRegistry

log = logging.getLogger(__name__)

SOURCE = "tulos.poytajaakiekko.fi"
OUTPUT = "finland_results.parquet"
BASE = "https://tulos.poytajaakiekko.fi"
TOURNAMENT_BASE = 4_000_000_000
STAGE_BASE = 4_100_000_000
LOCAL_BASE = 30_000_000
TYPE_NAMES = {"OPEN": "", "VETERANS": "Veterans", "JUNIORS": "Juniors", "WOMEN": "Women", "CUSTOM": ""}


class ResultsNeedAccess(RuntimeError):
    """The results endpoint needs the site's API key: ask the association for access (README)."""


def fetch_events(ctx: RunContext) -> list[dict]:
    path = ctx.source_dir("finland") / "raw" / "events.json.gz"
    if not ctx.offline:
        resp = ctx.client.get(f"{BASE}/api/events?limit=500")
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(resp.content, mtime=0))
    if not path.exists():
        return []
    return json.loads(gzip.decompress(path.read_bytes()))["events"]


def sub_tournaments(events: list[dict]) -> list[dict]:
    """One entry per finished sub-tournament (Open / Veterans / Juniors ...), oldest first."""
    out = []
    for ev in events:
        if ev.get("status") != "FINISHED":
            continue
        for t in ev.get("tournaments") or []:
            kind = TYPE_NAMES.get(t.get("tournamentType", ""), str(t.get("tournamentType", "")).title())
            if t.get("tournamentType") == "CUSTOM":  # side tournaments carry their own name ("Haastajasarja")
                kind = t.get("customType") or (t.get("name") if t.get("name") != ev["name"] else "") or "Custom"
            out.append({
                "tournament_id": t["id"], "tournament_slug": t.get("slug"), "event_id": ev["id"],
                "event_slug": ev.get("slug"), "season": (ev.get("season") or {}).get("slug"),
                "date": str(t.get("startDate") or ev.get("startDate"))[:10],
                "name": ev["name"] + (f" – {kind}" if kind else ""), "event_type": ev.get("eventType"),
                "url": f"{BASE}/{(ev.get('season') or {}).get('slug')}/{ev.get('slug')}/{t.get('slug')}",
            })
    return sorted(out, key=lambda r: (r["date"], r["event_slug"] or "", r["tournament_slug"] or ""))


def player_id(mapper: PlayerMapper, registry: IdRegistry, cuid: str, world_ranking_id, name: str = "") -> int:
    """ITHF id = worldRankingID when present; otherwise a stable local id keyed by the site's player cuid."""
    local = registry.get(cuid, name=name)
    return mapper.resolve(f"fi:{cuid}", ithf=to_int(world_ranking_id), local_id=local)


def probe_results(ctx: RunContext, tournament: dict) -> dict:
    """Fetch one tournament's results; raises ResultsNeedAccess while the endpoint requires the API key."""
    url = f"{BASE}/api/tournaments/{tournament['tournament_slug'] or tournament['tournament_id']}"
    try:
        resp = ctx.client.get(url)
    except AccessDenied as exc:
        raise ResultsNeedAccess(str(exc)) from exc
    if resp.status_code == 200 and "Invalid API access" not in resp.text:
        return resp.json()
    raise ResultsNeedAccess(f"{url} -> {resp.status_code} {resp.text[:80]}")


def run(ctx: RunContext) -> pd.DataFrame | None:
    sdir = ctx.source_dir("finland")
    events = fetch_events(ctx)
    subs = sub_tournaments(events)
    t_reg = IdRegistry(sdir / "tournament_ids.csv", TOURNAMENT_BASE + 1, ("name",))
    for t in subs:
        t_reg.get(t["tournament_id"], name=t["name"])
    t_reg.save()
    print(f"\n===== {SOURCE}: {len(events)} events, {len(subs)} finished sub-tournaments indexed =====")
    if ctx.offline or not subs:
        return None
    try:
        probe_results(ctx, subs[-1])
    except ResultsNeedAccess as exc:
        print(f"Results need the site's API key ({exc}). Nothing written; see README 'Finland'.")
        log.warning("finland: results endpoint still needs access")
        return None
    raise NotImplementedError(
        "finland: the results endpoint now answers. Save a few responses as tests/finland fixtures and write the "
        "transform (one row per game) against them.")
