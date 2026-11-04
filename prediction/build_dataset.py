"""Assemble one deduplicated game table the same way the H2H site does.

Uses the H2H repo's own loaders (scripts/build_h2h.py) so ids, aliases and cross-source
dedupe match what the site rates. Writes games.parquet sorted in playing order.
"""
import sys, argparse
from pathlib import Path
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--h2h", default="/home/user/amundfylling/table-hockey-h2h-cloudflare")
ap.add_argument("--scorpion", default="/home/user/amundfylling/Scorpion-Scraper-2.0/data")
ap.add_argument("--extra", nargs="+", default=[
    "/home/user/amundfylling/bordshockey.net-scraper/data/bordshockey_results.parquet",
    "/home/user/amundfylling/table-hockey-eu-fetch/data/table_hockey_eu_results.parquet",
    str(Path(__file__).resolve().parent.parent / "data/trefik_results.parquet"),
    str(Path(__file__).resolve().parent.parent / "data/galdahokejs_results.parquet"),
    str(Path(__file__).resolve().parent.parent / "data/escore_results.parquet"),
])
ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "games.parquet"))
args = ap.parse_args()

sys.path.insert(0, str(Path(args.h2h) / "scripts"))
import build_h2h as b  # noqa: E402

players, _ = b.load_players(Path(args.scorpion) / "players_data.csv", {})
name_index = b.build_unique_player_name_index(players)
frames = [b.read_matches_parquet(Path(args.scorpion) / "scraped_matches.parquet").assign(src="sportscorpion")]
for p in args.extra:
    frames.append(b.read_extra_matches_parquet(Path(p), name_index).assign(src=Path(p).stem))
m = pd.concat(frames, ignore_index=True)
levels = b.load_tournament_levels(Path(args.scorpion) / "tournament_metadata.csv")
m["tournament_level"] = m["tournament_id"].map(lambda t: levels.get(int(t)) if pd.notna(t) else None)
n0 = len(m)
m = b.deduplicate_overlapping_source_matches(m, {})
print(f"{n0} rows, {n0-len(m)} cross-source duplicates removed")

# Alias groups share one id
canon = {}
for g in b.load_alias_groups(Path(args.h2h) / "public/aliases.json"):
    ids = [int(x) for x in g]
    for x in ids:
        canon[x] = ids[0]
for c in ("player1_id", "player2_id"):
    m[c] = m[c].astype("int64").map(lambda x: canon.get(x, x))
m = m[m.player1_id != m.player2_id]
m = m.loc[b.ratings._playing_order(m)] if hasattr(b, "ratings") else m
keep = ["date_dt", "tournament_id", "tournament_name", "tournament_level", "stage_id", "stage_sequence",
        "stage_name", "stage_type", "round_number", "playoff_game_number", "overtime",
        "player1_id", "player2_id", "goals_player1", "goals_player2", "src"]
keep = [k for k in keep if k in m.columns]
m = m[keep].reset_index(drop=True)
print(m.columns.tolist()); print(m.src.value_counts()); print(len(m), m.date_dt.min(), m.date_dt.max())
m.to_parquet(args.out, index=False)
