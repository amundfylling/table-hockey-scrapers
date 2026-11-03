# table-hockey-scrapers

Collects table hockey match results from four sources that the
[H2H site](https://github.com/amundfylling/table-hockey-h2h-cloudflare) does not ingest yet, and writes one
Parquet file per source in exactly the schema of
[bordshockey.net-scraper](https://github.com/amundfylling/bordshockey.net-scraper) and
[table-hockey-eu-fetch](https://github.com/amundfylling/table-hockey-eu-fetch):

| Module | Source | Covers | Output |
|---|---|---|---|
| `trefik` | stiga.trefik.cz | Czech Cup, Czech championships, Czech Open, 2000– | `data/trefik_results.parquet` |
| `galdahokejs` | galdahokejs.lv | Latvian events 2022-05-01 … 2025-11-30 | `data/galdahokejs_results.parquet` |
| `escore` | escore.live | Latvian events from 2025-12-01, Ukraine Cup 2026 | `data/escore_results.parquet` |
| `finland` | tulos.poytajaakiekko.fi | Finnish ranking tournaments 1992– | `data/finland_results.parquet` |

`data/all_results.parquet` is the four files concatenated, for consumers that prefer a single file.

## Status

| Part | State |
|---|---|
| Shared layer (`scrapers/common/`): HTTP client, id mapper, registries, schema writer, duplicate check | done, tested |
| `python -m scrapers.all`, nightly workflow | done |
| `trefik` | **not written yet**: the build environment's network policy blocked stiga.trefik.cz |
| `galdahokejs` | **not written yet**: galdahokejs.lv blocked (needs the shared Trefik SW parser from `trefik`) |
| `escore` | **not written yet**: escore.live blocked |
| `finland` | **not written yet**: tulos.poytajaakiekko.fi blocked; access question still open (below) |

Parsers are only written against real pages saved from each site (they become the test fixtures), so the
source modules currently raise `NotImplementedError`. The workflow step for each source fails until then,
while the others (and the combine step) still run.

## Usage

```bash
pip install -r requirements.txt
python -m scrapers.trefik                 # one source: crawl new/in-progress events, write its Parquet
python -m scrapers.all                    # all sources, then all_results.parquet + duplicate check
python -m scrapers.all --combine-only     # only rebuild all_results.parquet and the duplicate check
python -m scrapers.<source> --offline     # rebuild from data/<source>/raw only
python -m pytest -q
```

Common options: `--players-csv PATH|URL`, `--ranking PATH|URL`, `-v`.

## Layout

```
scrapers/common/http.py        polite client: 1 req/s per host (or robots Crawl-delay), retries with backoff,
                               User-Agent, robots.txt, raw cache, encoding detection
scrapers/common/players.py     Sportscorpion / ITHF player id mapping and name matching
scrapers/common/registry.py    committed CSV id registries (ids assigned once, never reused)
scrapers/common/schema.py      output schema, validation, deterministic sort, Parquet writer
scrapers/common/dedupe.py      cross-source duplicate tournament check
scrapers/common/overlaps.py    Sportscorpion tournament list / table-hockey.eu Parquet for overlap skips
scrapers/common/report.py      end-of-run report
scrapers/common/context.py     reference data loaded once per run and shared by all sources
scrapers/<source>/             one module per source, `python -m scrapers.<source>`
scrapers/all.py                `python -m scrapers.all`
data/<source>/raw/             raw responses (committed; finished events are never re-fetched)
data/<source>/*_ids.csv        id registries (committed)
data/<source>/name_matches.csv every name-based id decision, for review
data/duplicate_check.csv       output of the cross-source check
```

## Output schema

Identical column order and dtypes to the existing scrapers (pandas `Int64` / `string`, Arrow `int64` /
`large_string`); `tests/common/test_schema.py` checks this against real rows from table-hockey-eu-fetch.
One row per game (one row per game of a playoff series). Rows are sorted by
`Date, TournamentID, StageSequence, RoundNumber, SourceMatchID`, so nightly commits only change when the data does.

Skipped, and counted by reason in the run report: byes, unplayed games, games without a score,
walkovers/forfeits, and results carried forward from an earlier stage. Round-robin draws are kept.
`Overtime` is `No` when the source cannot tell.

## Player ids

The H2H site's canonical id is the Sportscorpion `PlayerID`. `players_data.csv` and the ITHF `ranking.txt` are
downloaded once per run (`data/_shared/`, not committed) and shared by every source.

1. Known ITHF id that matches a `RankingID` in `players_data.csv`: that `PlayerID` (lowest one if a RankingID is
   duplicated, as in table-hockey-eu-fetch).
2. Any other known ITHF id: `9_000_000 + ithfId`.
3. Otherwise a source-local id (ranges below), stable across runs.

Name matching (where a source needs it) folds diacritics, lowercases and compares the *set* of name tokens
("Plešák Pavel" = "Pavel Plesak"), requires the same nation when the source gives one, and only accepts a
unique match. Every decision goes to `data/<source>/name_matches.csv`. The mapping is re-run every run, so a
player who later gets an ITHF id or appears on Sportscorpion switches to the real id. The report prints how
many players were mapped by each route.

| Source | TournamentID | StageID | Local player ids |
|---|---|---|---|
| trefik | 3_000_000_000 + n | 3_100_000_000 + n | 20_000_000 + idpl, else 21_000_000+ from `player_ids.csv` |
| finland | 4_000_000_000 + n | 4_100_000_000 + n | 30_000_000+ from `player_ids.csv` (key: site cuid) |
| escore | 5_000_000_000 + event id | 5_100_000_000 + n | 40_000_000 + escore player id |
| galdahokejs | 6_000_000_000 + n | 6_100_000_000 + n | 50_000_000+ from `player_ids.csv` (key: folded name + club) |

`n` comes from committed registries under `data/<source>/`.

## Overlaps

- Latvia: Sportscorpion until 2022-04, galdahokejs.lv 2022-05-01 … 2025-11-30, escore.live from 2025-12-01,
  table-hockey.eu from 2026-09. galdahokejs skips events in Sportscorpion's `tournament_metadata.csv`
  (Latvia, ±1 day); escore skips events on table-hockey.eu (same name and date). Both log what they skip.
- `python -m scrapers.all` flags tournaments from two different sources with the same date (±1 day) and a
  similar name (years and generic words like "Cup"/"Open" ignored) in `data/duplicate_check.csv`.
- `SourceTournamentID` is kept so the site can dedupe World Tour events that may later appear elsewhere.

## Crawl rules

At most one request per second per host (more if robots.txt sets a Crawl-delay), timeouts, retries with
exponential backoff, User-Agent `table-hockey-h2h-scraper/1.0 (+https://github.com/amundfylling/table-hockey-scrapers)`.
robots.txt is respected (an HTML "robots.txt", like Finland's 404 page, counts as no rules). No login, admin or
write endpoints; a 401/403 raises `AccessDenied` and is never worked around.

## Findings so far

- **Finland:** the `spjass` GitHub account only has old public repos (`TH-Results`, `THResults`, a 2013/2015
  Android result app); the source or a data export of tulos.poytajaakiekko.fi is not public there.
  `/api/tournaments/<id>` answered `{"error":"Invalid API access"}` to an anonymous GET in an earlier probe; it
  still has to be checked how the public result pages load their data before deciding whether access must be
  requested.

## Known gaps

To be filled in per source as each one is built (team events, old seasons without ids, Google Sheets results on
galdahokejs.lv, etc.).

## Nightly run

`.github/workflows/scrape_nightly.yaml` runs at 04:00 UTC: tests, one step per source (`continue-on-error`, so one
failing source doesn't block the others), the combine + duplicate check, then commits changed `data/`. The run is
marked failed afterwards if any source failed.
