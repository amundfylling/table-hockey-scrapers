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
| `trefik` | done: 360 events 2000–2026, ~302k games (see "stiga.trefik.cz" below) |
| `galdahokejs` | done: 44 events 2023-09 – 2025-11, ~32.6k games (see "galdahokejs.lv" below) |
| `escore` | done: 28 events 2026-01 – 2026-09, ~12.4k games (see "escore.live" below) |
| `finland` | event index only; results need an API key; access email drafted (see below) |

Parsers are written against real pages saved from each site (kept as test fixtures under `tests/<source>/`).
The first combined run gave 347k games in `all_results.parquet` and no suspicious cross-source pairs in
`duplicate_check.csv`.

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
scrapers/common/id_report.py   names with more than one id across Sportscorpion and the Parquets
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
2. Known ITHF id that `players_data.csv` lacks, but the same name (and nation: the source's, else ranking.txt's)
   is there exactly once under a PlayerID with an empty or different RankingID: that `PlayerID`
   (`ithf_name_sportscorpion`; a candidate whose RankingID belongs to someone else in ranking.txt is not used).
3. Any other known ITHF id: `9_000_000 + ithfId`.
4. No ITHF id, but a unique name match in `players_data.csv`: that `PlayerID` (`sportscorpion_name`; all sources;
   Trefik only when no other Trefik player has that name).
5. Otherwise a source-local id (ranges below), stable across runs. Local ids stay in the registries even when a
   player stops using them; they are never renumbered or reused.

Name matching folds diacritics, lowercases and compares the *set* of name tokens ("Plešák Pavel" =
"Pavel Plesak"), and only accepts a unique match. When both sides have a nation it must match; a
`players_data.csv` row without a country still counts against uniqueness. Every decision goes to
`data/<source>/name_matches.csv` (column `method`). The mapping is re-run every run, so a player who later gets an
ITHF id or appears on Sportscorpion switches to the real id. The report prints how many players were mapped by
each route.

**Guard:** if a name-based Sportscorpion id would put the same id on both sides of a game (two different source
players who play each other in one tournament), that name match is refused for the player, the rows are rebuilt,
and the decision is logged as `rejected_played_each_other`.

`python -m scrapers.all` also writes `data/player_id_report.csv`: names (folded, any word order) that still have
more than one id across `players_data.csv` and the Parquets, with game counts per source, for manual merging in
the site's `aliases.json`.

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

## tulos.poytajaakiekko.fi (Finland) – waiting for access

- **Public:** `/api/events?limit=500` (all 217 events with their sub-tournaments: Open, Veterans, Juniors, Women,
  side tournaments), `/api/events/<slug>` and `/api/players/search?q=` (with `worldRankingID` = ITHF id).
- **Not public:** the results. The site's pages load them from `/api/tournaments/<slug>` with an internal API key
  sent by their JavaScript; without it the endpoint answers `401 {"error":"Invalid API access"}`. Sending that key
  from a scraper would be getting around the access check, so the module does not.
- **What runs now:** `python -m scrapers.finland` fetches the event index, gives every finished sub-tournament its
  permanent TournamentID (`data/finland/tournament_ids.csv`, keyed by the site's tournament id; name = event name +
  type when not Open, e.g. `215. Tampere – Veterans`), and probes one results URL so the log shows when access
  starts working. No Parquet is written yet. Player ids: `worldRankingID` → ITHF/Sportscorpion as everywhere,
  else 30_000_000+ keyed by the site's player id (`player_id()`).
- **Access request:** draft in `docs/finland_access_email.md`. The old `spjass` GitHub repos (`TH-Results`,
  `THResults`) don't contain the site's data.

## stiga.trefik.cz

- **Discovery:** `stolni-hokej.cz/pohar.html` (re-read every run) lists every season. Season statistics (`data`,
  `data_new`, `ted20xx`) are ignored. National championships are split into one tournament per category: from the
  index row (2023+), `kategorie.aspx` (2018–2022) or the old hub pages (`index.htm` with "Turnaj jednotlivců /
  žen / juniorů / veteránů", 2000–2017). Name: `Czech Cup <place> <year>`, `Czech Open <year>`,
  `Moravia Open <year>`, `Czech Championship <year> – <category>`.
- **Pages:** from the tournament page every result page in the same folder is followed (`kriz*`, `*cross*`,
  `*umisteni*`, `*playoff*`, `*_list*`, `*_wr*`, `*ranking*`). Identical cross-tables shown on several pages are read
  once. The 2026 events use a JSON file (`<tour>/m-<src>.json`) behind `ranking.html`, read directly.
- **Games:** cross-table cells above the diagonal (each game once; "8:1 + 7:1" = two games), play-off series one row
  per game ("P" = overtime → `Overtime = Yes`). Cells marked "K" are skipped: in final groups they are results
  carried over from the basic group, in the play-off they are walkovers.
- **Names:** cross-tables print short labels ("Kr Lebl", "L.Turoň", "ml Chylík"). They are matched to the event's
  full names (final table, round tables, play-off and participants pages); a name already placed in another group of
  the same phase is excluded, and pages without any full names fall back to every name seen on the site within ±3
  seasons. Only unique matches are used.
- **Ids:** Trefik `idpl` comes from player links (final table, play-off pages, participants list, the 2026 JSON) and
  is carried to unlinked events by unique full-name match. ITHF ids come from the participants/WR lists
  (`ithf/ranking/player.aspx?ID=`) and the 2026 JSON (`wr_id`), else a unique `ranking.txt` name match (CZE preferred).
- **Checked:** every game of Patrik Petr at Němčice 2023 (38) and of Rainers Kalniņš at Czech Open 2023 (58) equals
  their `thstats/overview_b.aspx` pages (tests/trefik).

## galdahokejs.lv

- **Discovery:** the Joomla menu from the home page (plus the Riga Cup history, ECh 2024 and `turniri` pages), every
  section/season page from 2022 on, up to three levels deep. Links to Trefik SW folders (`/stats/<folder>/…`) are
  collected; links to Sportscorpion, tablehockey.me, escore and table-hockey.eu are not followed (covered elsewhere).
  The 2021/22 and 2022 season pages link their results to Sportscorpion, so the first galdahokejs events are from
  September 2023.
- **Parsing:** the shared Trefik SW parser (`scrapers/common/trefik_sw.py`). Pages declare windows-1257 but older
  ones contain windows-1250 bytes ("Kalninš"); such pages are decoded as 1250 and each player id keeps its most used
  spelling. Where an event has no full-name list (Amatieru Līga: only "Ra Ladusans" labels), labels are matched to
  names elsewhere on the site, then to Latvian players in `players_data.csv`/`ranking.txt` (unique matches only).
- **Events:** folders of one event (Riga Cup qualification + divisions + top 72, `25RK`/`25RKMain`/`25RK72`) are one
  tournament, stages prefixed `Qualification`, `Divisions`, `Top 72`. ECh 2024 individual events are named
  `European Championship 2024 – <category>`; a year is added to names without one. Team championships are skipped.
- **Window:** 2022-05-01 … 2025-11-30; events in Sportscorpion's list (Latvia, ±1 day) are skipped (none in the
  window today). Google Sheets links are listed in `data/galdahokejs/google_sheets.csv` (52) but not parsed.

## escore.live

- **Discovery:** event ids 1, 2, … from `/events/<id>/particiants` (the site's own spelling) until 25 ids in a row are
  missing or private; `/api` is disallowed by robots.txt and not used. Only `table_hockey` singles events are kept
  (the site also hosts table tennis and beach volleyball).
- **Games:** each result tab (`/events/<id>/net/<net>`) gives groups and elimination trees; a best-of series gives one
  row per set (`set_score`, `set_overtimes`). Hidden/pending games and byes are skipped.
- **Names:** TournamentName = competition name (`Latvijas Kauss 2025/26 #2`), plus the event name when the competition
  has several singles events (`Ādažu galda hokeja līga - 1. posms – Pro 2026`). Stages: `Basic groups …` (first tab with
  groups), `Final groups …`, `Playoff [<bracket>] 1/8 … Final`, placement brackets `Playoff 5.-8. place 1/2`.
- **Ids:** `ithf_id` on the player, else ranking.txt (player's nation), else Sportscorpion name + country, else
  40_000_000 + escore player id. Events from before 2025-12-01 and events also on table-hockey.eu (same name, ±1 day)
  are skipped.

## Known gaps

- **trefik:** season 1998/99 (`cz_turnaje/99/…`) is linked from the index but every page is 404. Team championships
  (`mrdr`, "Turnaj družstev") are skipped: their pages are team tables, not individual games with both players.
  ~1,100 group games (0.4%) are left out because a short label fits two players of the same event (e.g. two
  "J.Sládek", "A./m.Šrajer"); each case is listed in the run report. `turnaje2010/mr` only links the individual
  event from the index (the other 2010 categories are not reached). Round numbers are only known where the page has
  round tables (most events from ~2016); older group games have `RoundNumber` null.

- **galdahokejs:** Latvian events May 2022 – Aug 2023 are neither on galdahokejs stats pages nor on Sportscorpion's
  list (some may be in the unparsed Google Sheets). Riga Cup 2025 (6–7 Dec) is after the window, and on escore.live
  it only has a participant list, so it is in no source. ~740 group games (2%) are left out because a short label
  matches no single player. Team events (ECh 2024 teams, WT) are skipped.
- **escore:** "Izlases treniņnometne 2026" (national team training camp, 589 games) is kept as an event; say if
  training events should be dropped. The Ukrainian Open Championship 2026/27 stages are only scheduled so far.

## Nightly run

`.github/workflows/scrape_nightly.yaml` runs at 04:00 UTC: tests, one step per source (`continue-on-error`, so one
failing source doesn't block the others), the combine + duplicate check, then commits changed `data/`. The run is
marked failed afterwards if any source failed.
