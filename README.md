# Euroleague Shot Profiles

**Live app:** https://baranerdogan11.github.io/Euroleague-Shot-Profiles/

Player stats and animated shot charts for every Euroleague player in the 2026-27 season, updated game by game
from the league's official feeds. Pick a team, pick a player: season numbers, shooting splits, accuracy by zone
of the floor, and every field-goal attempt of the season plotted on a half court, made and missed, played back
in order.

## What it shows

- All 20 clubs with crests; player dropdown limited to the selected club's registered roster
- Media-day photo, number, position, height, age, nationality, games and minutes
- Per-game PTS, REB, AST, STL, BLK, TOV, PIR and fouls drawn
- 2P%, 3P%, FT% and true shooting, with makes over attempts
- Five-zone accuracy: rim, paint, mid-range, corner 3, above-break 3
- Animated shot chart with made / missed filter, single-game filter, and a Zones view shading the floor by FG%
- Hover any shot for the game, quarter, distance, fast break and second chance
- Game log
- 2D and 3D shot charts: the 3D view (Three.js, loaded on demand) replays every attempt as a ball in flight with camera presets and orbit
- Before a club's first game the page shows the roster and the date of the opener; stats and charts fill in as games are played
- Deep links: `#ULK`, `#ULK/P007200`, `#ULK/P007200/zones` (club code, player id, optional zones view)

## How it runs

A GitHub Actions workflow (`.github/workflows/update.yml`) runs every night at 02:30 UTC, after the last game
of the day, and can be started by hand from the Actions tab. Each run:

1. restores the feed cache, so only new games are downloaded
2. runs the gate's own tests (`tests/test_checks.py`), which prove the checks catch what they should
3. fetches new games, roster changes (re-pulled every night, with start and end dates) and photos (`fetch_season.py`)
4. runs the raw-feed gate (`checks.py`)
5. builds the warehouse (`warehouse.py`): six Parquet tables under `warehouse/E2026/`, the silver layer;
   see [`warehouse/SCHEMA.md`](warehouse/SCHEMA.md)
6. runs 23 SQL assertions over the warehouse (`warehouse_tests.py`): key uniqueness, referential integrity,
   schedule completeness, and per player per game reconciliation of plotted attempts and makes with the box score;
   any failure stops the run before anything is published
7. scores every shot with the xFG model (`model/score.py`), see below
8. builds the site from the warehouse with SQL (`build.py`, the gold layer) and commits it; GitHub Pages deploys within a minute

The assertions write `teams/E2026/status.json` (games, shots, box lines, tests, failures, time) and the page footer
shows the last verdict. A failed run leaves the previous good build live and uploads the status report as a
workflow artifact. Roster stints mean a player who changes club mid-season keeps his full season under his
current club.

## Expected field goal model (xFG)

`model/xfg.py` trains a gradient-boosted classifier on a past season's warehouse to estimate the probability
that a shot goes in from its context: location, distance, angle, shot value, zone, quarter and clock, score
margin, home court, fast break, second chance, points off turnover. Shooter quality is a separate, leak-free
feature: each shooter's shrunk running residual (made minus xFG) over his earlier shots only, so the model never
sees the outcome it predicts. Validation is time-based (the last quarter of the season's games held out) against
constant, zone-average and distance-bin baselines; metrics, calibration by decile and permutation importance are
written to `model/model_card.json`.

Trained on 2025-26 (51,750 shots, 329 shooters), held-out log loss 0.630 against 0.645 for zone-average FG%
and 0.692 for a constant, AUC 0.67, calibrated within 1.5 points in every decile. Distance dominates; the shooter
term adds a small, real gain. A first version scored 0.497 and was discarded: the feed's fast-break,
second-chance and points-off-turnover flags are only set on made shots, and the running score includes the
basket just made, so both leaked the label. They are excluded and the margin is taken before the shot.
`model/score.py` scores the current season nightly, carrying last season's
shooter effects forward as decayed priors. The page shows each player's xFG, actual versus expected points per
attempt, and points above expectation; every shot's tooltip carries its xFG.

## Data layers

| Layer | Where | Produced by | Tests |
|---|---|---|---|
| Bronze | `cache/E2026/` (raw feed JSON, not committed) | `fetch_season.py` | `checks.py` |
| Silver | `warehouse/E2026/*.parquet` | `warehouse.py` | `warehouse_tests.py` (23 assertions), `tests/test_warehouse.py` (real-game fixture) |
| Gold | `teams/E2026/*.json`, `index.html` | `build.py` | rendered site |

## Update by hand

```bash
pip install -r requirements.txt
python fetch_season.py E2026   # clubs, crests, rosters, photos, then shots and box scores for new games
python checks.py E2026 && python warehouse.py E2026 && python warehouse_tests.py E2026
python build.py E2026          # writes index.html and teams/E2026/*.json from the warehouse
git add -A && git commit -m "Update after round" && git push   # GitHub Pages redeploys in about a minute
```

`fetch_season.py` caches every game, roster and image under `cache/`, so a rerun only downloads what is new.

## Layout

- `index.html`: the page (loads a club's JSON when it is selected)
- `teams/E2026/index.json`, `teams/E2026/<CLUB>.json`: compact per-club data (stats, game log, shots)
- `photos/<player>.webp`, `logos/<CLUB>.png`: media-day photos and crests
- `warehouse/E2026/*.parquet`: the queryable season warehouse (schema in `warehouse/SCHEMA.md`)
- `fetch_season.py`, `checks.py`, `warehouse.py`, `warehouse_tests.py`, `build.py`, `template.html`: the pipeline and page source

The page fetches its data files, so serve the folder over HTTP to run it locally
(`python -m http.server 8000`, then open http://localhost:8000/); opening `index.html` directly from disk will not load data.

## Data

Rosters, crests, photos, box scores and shot coordinates come from the Euroleague official API and live feeds.
Coordinates are in centimetres relative to the basket; the court is drawn to FIBA dimensions.
