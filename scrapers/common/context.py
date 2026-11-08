"""Things loaded once per run and shared by every source."""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from .http import PoliteClient
from .players import ITHF_ARCHIVE_URL, PLAYERS_CSV_URL, RANKING_URL, ReferenceData, load_reference

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


@dataclass
class RunContext:
    client: PoliteClient
    ref: ReferenceData
    offline: bool = False
    data_dir: Path = DATA
    extra: dict = field(default_factory=dict)

    def source_dir(self, source: str) -> Path:
        return self.data_dir / source


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--offline", action="store_true", help="only use data/<source>/raw, fetch nothing new")
    parser.add_argument("--players-csv", default=PLAYERS_CSV_URL, help="Sportscorpion players_data.csv (URL/path)")
    parser.add_argument("--ranking", default=RANKING_URL, help="ITHF ranking.txt (URL/path)")
    parser.add_argument("--ithf-archive", default=ITHF_ARCHIVE_URL,
                        help="name -> ITHF id list that includes inactive players (URL/path, '' to turn off)")
    parser.add_argument("-v", "--verbose", action="store_true")


SHARED = DATA / "_shared"  # not committed; lets the per-source workflow steps share one download
SHARED_MAX_AGE = 6 * 3600


def _shared_copy(client: PoliteClient, source: str | None, name: str) -> str | None:
    """Download a reference file once per run (reused for 6 hours), so every source sees the same data."""
    if not source or not source.startswith(("http://", "https://")):
        return source
    path = SHARED / name
    if path.exists() and time.time() - path.stat().st_mtime < SHARED_MAX_AGE:
        return str(path)
    try:
        resp = client.get(source)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).error("could not download %s: %s", source, exc)
        return str(path) if path.exists() else (None if name in ("ranking.txt", "ithf_archive.csv") else source)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return str(path)


def build_context(args: argparse.Namespace) -> RunContext:
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    client = PoliteClient()
    players = _shared_copy(client, args.players_csv, "players_data.csv")
    ranking = _shared_copy(client, args.ranking, "ranking.txt")
    archive = _shared_copy(client, getattr(args, "ithf_archive", None), "ithf_archive.csv")
    ref = load_reference(players, ranking, client, ithf_archive=archive)
    return RunContext(client=client, ref=ref, offline=args.offline)
