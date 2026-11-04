# Match outcome prediction

Goal: the best possible win/draw/loss probabilities for a game, by any method. Compared against
the H2H site's current forecast (Glicko-2 with goal difference plus a head-to-head term,
`table-hockey-h2h-cloudflare/scripts/ratings.py`) and plain Elo.

## Result

Test set: every game from 2022-01-01 to 2026-11-03 (553,813 games). Models are fitted on 2005–2020,
early-stopped on 2021, then refitted on 2005–2021. Lower log loss is better.

| Model | Log loss | Accuracy | Brier | RPS |
|---|---|---|---|---|
| Constant (50/50 + draw rate) | 0.9554 | 0.509 | 0.588 | 0.247 |
| Elo K=24 (draw model fitted) | 0.7753 | 0.671 | 0.448 | 0.178 |
| Goal-difference Elo (draw model fitted) | 0.7727 | 0.673 | 0.446 | 0.177 |
| **Site Glicko-2 + H2H, as published** | **0.7572** | **0.680** | 0.436 | 0.172 |
| Logistic regression on site rating + Elos + form | 0.7562 | 0.680 | 0.436 | 0.172 |
| Site Glicko-2 + H2H, recalibrated with game context (playoff, game no., level, source, year) | 0.7286 | 0.680 | 0.430 | 0.171 |
| LightGBM, all features except game context | 0.7322 | 0.684 | 0.427 | 0.169 |
| **LightGBM, all features** | **0.7186** | **0.684** | **0.424** | **0.168** |

The final model lowers log loss by 0.039 (5.1%) against the site forecast and raises accuracy from
68.0% to 68.4%. It is better in every test year (2022–2026), every source, and every slice by
player experience and head-to-head history (`slices.csv`).

Where the gain comes from:

* **Playoff games can't end in a draw** (0–1% draws vs 12–14% in round robins). The site gives every
  game the same ~12% draw chance. Just recalibrating the site's own rating gap with game context
  gets log loss to 0.7286, which is most of the gain on playoff games (0.717 → 0.600).
* **Extra signals in round-robin games** (0.768 → 0.751): Elo variants, an online Poisson
  attack/defence model (expected goals each side), recent form vs. expectation, draw tendency,
  how often a player is in upsets, in-tournament form, and head-to-head history. The Glicko rating
  gap is still by far the strongest single feature, so the ratings stay as inputs.
* Debutants and players with few games gain the most (0.703 → 0.642 for debut games).

Accuracy barely moves because the favourite is usually the same; the gain is in how confident the
probabilities are, which is what log loss measures.

## Leakage rules

* Every feature for a game is computed from games strictly before it in the site's playing order
  (`date, tournament, stage, round, playoff game`), the same order the site's ratings use.
* Player 1 / player 2 position is not used: in trefik and galdahokejs player 1 wins ~70% of
  round-robin games, so the column order carries result information. The model is trained on both
  orientations of each game and predicts the average of both, so swapping players swaps the
  probabilities exactly.
* Hyperparameters were chosen on 2021 only; 2022+ was used once for the numbers above.
* The site's Glicko-2 settings were tuned on 2017–2021 by the earlier backtest, so the baseline is
  not handicapped. `features.py` ports `ratings.py` exactly (same ratings and forecasts, checked).

## Data

`build_dataset.py` assembles the games with the H2H site's own loaders (Sportscorpion, bordshockey.net,
table-hockey.eu, trefik, galdahokejs, escore; site aliases and cross-source dedupe):
1,634,895 games 1982–2026.

## Run

```bash
pip install pandas pyarrow numba lightgbm scikit-learn scipy
python build_dataset.py   # needs clones of table-hockey-h2h-cloudflare, Scorpion-Scraper-2.0,
                          # bordshockey.net-scraper, table-hockey-eu-fetch (paths are arguments)
python make_features.py   # ~45 s
python train.py           # ~30 min on 4 cores; writes results.json, test_predictions.parquet, lgbm_model.txt
python slices.py          # slices.csv
```

## Possible next steps

* Explicit series state for playoffs (games won so far in the current series).
* Hyperparameter search and a smaller learning rate; ensembling a few seeds.
* Predicting the goal difference directly (ordinal model) and deriving W/D/L from it.
