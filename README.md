# Euroleague Shot Profiles

**Live app:** https://baranerdogan11.github.io/Euroleague-Shot-Profiles/

Player stats and animated shot charts for every Euroleague player, updated game by game from the league's
official feeds. Pick a team, pick a player: season numbers, shooting splits, accuracy by zone of the floor,
and every field-goal attempt of the season plotted on a half court, made and missed, played back in order.

Demo: Fenerbahçe Beko 2025-26, 43 games, 2,664 shots, media-day photos from the 2026-27 campaign.

## What it shows

- Team dropdown, then a player dropdown limited to that team's roster
- Media-day photo, number, position, height, age, nationality, games and minutes
- Per-game PTS, REB, AST, STL, BLK, TOV, PIR and fouls drawn
- 2P%, 3P%, FT% and true shooting, with makes over attempts
- Five-zone accuracy: rim, paint, mid-range, corner 3, above-break 3
- Animated shot chart with made / missed filter, single-game filter, and a Zones view shading the floor by FG%
- Hover any shot for the game, quarter, distance, fast break and second chance
- Game log
- Deep links: `index.html#ULK/P002100/zones` (team code, player id, optional `zones`)

## Run it

```bash
pip install -r requirements.txt
python fetch_team.py ULK E2025   # roster, photos, box scores, shot coordinates; cached per game
python build.py                  # writes index.html
open index.html
```

`fetch_team.py` pulls only games that are not yet in `cache/`, so re-running it after each round adds the new
games and `build.py` refreshes the page. Any club works: `python fetch_team.py OLY E2026`. Every club fetched
appears in the team dropdown.

## Data

Rosters, photos, box scores and shot coordinates come from the Euroleague official API and live feeds.
Coordinates are in centimetres relative to the basket; the court is drawn to FIBA dimensions.
`index.html` is a single self-contained file (photos embedded), so it can be hosted anywhere or opened directly.
