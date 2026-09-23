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
3. fetches new games, roster changes and photos (`fetch_season.py`)
4. runs the data-quality gate (`checks.py`): 20 clubs with plausible rosters, no duplicate or future games,
   every played game scored, every shot inside the court, and for every player in every game the plotted
   attempts reconcile exactly with the box-score attempts; any failure stops the run before anything is published
5. builds the site (`build.py`) and commits it; GitHub Pages deploys within a minute

The gate writes `teams/E2026/status.json` (games, shots, box lines reconciled, failures, warnings, time) and the
page footer shows the last verdict. A failed run leaves the previous good build live and uploads the status
report as a workflow artifact.

## Update by hand

```bash
pip install -r requirements.txt
python fetch_season.py E2026   # clubs, crests, rosters, photos, then shots and box scores for new games
python build.py E2026          # writes index.html and teams/E2026/*.json
git add -A && git commit -m "Update after round" && git push   # GitHub Pages redeploys in about a minute
```

`fetch_season.py` caches every game, roster and image under `cache/`, so a rerun only downloads what is new.

## Layout

- `index.html`: the page (loads a club's JSON when it is selected)
- `teams/E2026/index.json`, `teams/E2026/<CLUB>.json`: compact per-club data (stats, game log, shots)
- `photos/<player>.webp`, `logos/<CLUB>.png`: media-day photos and crests
- `fetch_season.py`, `build.py`, `template.html`: the pipeline and page source

The page fetches its data files, so serve the folder over HTTP to run it locally
(`python -m http.server 8000`, then open http://localhost:8000/); opening `index.html` directly from disk will not load data.

## Data

Rosters, crests, photos, box scores and shot coordinates come from the Euroleague official API and live feeds.
Coordinates are in centimetres relative to the basket; the court is drawn to FIBA dimensions.
