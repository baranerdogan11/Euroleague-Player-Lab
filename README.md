# Euroleague Player Lab

**Live app:** https://baranerdogan11.github.io/Euroleague-Player-Lab/ · **Live xFG API:** https://euroleague-xfg.onrender.com (docs at `/docs`)

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
- Hover any shot for the game, quarter, distance and its expected FG% (for a league-average shooter, and for the player himself)
- League values by zone and by shooting split next to every rate; rates on fewer than 10 attempts are greyed and carry a 95% interval
- Role strip: usage, true shooting, 3-point and free-throw rates, assist, turnover and rebound rates, on/off net rating, each ranked within the player's position group (per game or per 40 minutes for the counting stats)
- Play-by-play context on every shot: assisted or unassisted, and-ones, blocks, seconds into the possession; an assisted/unassisted filter on the chart, an assisted share per zone and a shot-timing table
- Shot diet against the position average, form over the last five games, home and away split, rest days, game pace and opponent defensive rating in the log
- Compare with any player of the same position, next to the position median
- Game log
- 2D and 3D shot charts: the 3D view (Three.js, loaded on demand) replays every attempt as a ball in flight with camera presets and orbit
- Before a club's first game the page shows the roster and the date of the opener; stats and charts fill in as games are played
- Deep links: `#ULK`, `#ULK/P007200`, `#ULK/P007200/zones` (club code, player id, optional zones view)

## How it runs

A GitHub Actions workflow (`.github/workflows/update.yml`) checks the games feed every 5 minutes on game evenings
(17:00 to 02:00 UTC) and runs the pipeline as soon as a game has been marked final since the last build, so a player's
page updates within about ten minutes of the final buzzer; a game still in progress is never fetched, because only
games the feed marks `result` count as played. It also runs every night at 02:30 UTC regardless, after the last game
of the day, and can be started by hand from the Actions tab. Each run:

1. restores the feed cache, so only new games are downloaded
2. runs the gate's own tests (`tests/test_checks.py`), which prove the checks catch what they should
3. fetches new games, roster changes (re-pulled every night, with start and end dates) and photos (`fetch_season.py`)
4. runs the raw-feed gate (`checks.py`)
5. builds the warehouse (`warehouse.py`): six Parquet tables under `warehouse/E2026/`, the silver layer, then the
   play-by-play layer (`events.py`): every event of every game and, per shot, whether it was assisted, an and-one,
   blocked, and how many seconds into the possession it came; see [`warehouse/SCHEMA.md`](warehouse/SCHEMA.md)
6. runs 26 SQL assertions over the warehouse (`warehouse_tests.py`): key uniqueness, referential integrity,
   schedule completeness, per player per game reconciliation of plotted attempts and makes with the box score, and
   play-by-play assists reconciled with the box score per club per game; any failure stops the run before anything
   is published (one distance check is a warning only)
7. scores every shot with the xFG model (`model/score.py`), see below
8. builds shooting profiles, shot quality versus shooting skill with shrinkage (`model/profile.py`)
9. writes validated scouting notes with Claude for players whose facts changed (`model/notes.py`, needs the `ANTHROPIC_API_KEY` secret)
10. builds the site from the warehouse with SQL (`build.py`, the gold layer): season stats, league benchmarks, role metrics, on/off, position ranks, the defence-adjusted expectation, the compare index and the league leaderboards
11. writes the monitoring snapshot (`model/monitor.py`) and commits everything; GitHub Pages deploys within a minute

The assertions write `teams/E2026/status.json` (games, shots, box lines, tests, failures, warnings, time) and the page footer
shows the check date, the game count and the verdict. A failed run leaves the previous good build live and uploads the status report as a
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
and 0.692 for a constant, AUC 0.67, calibrated within 4 points in every decile and within 2 in eight of ten. Distance dominates; the shooter
term adds a small, real gain. A first version scored 0.497 and was discarded: the feed's fast-break,
second-chance and points-off-turnover flags are only set on made shots, and the running score includes the
basket just made, so both leaked the label. They are excluded and the margin is taken before the shot.
`model/score.py` scores the current season nightly, carrying last season's
shooter effects forward as decayed priors. Every "expected" number on the page (the xFG row, the profile panel, the scouting note) uses the
context-only expectation, what a league-average shooter would do on the same shots, so the figures agree; the
shooter-aware probability appears only in the per-shot tooltip, labelled as his own.

## What the play-by-play adds, and what no feed has

The live API's PlayByPlay endpoint carries assists, fouls, blocks, substitutions and the scorer's clock. Assists are
logged after the make they belong to, so each make is marked assisted when an assist by the same club follows it
within the next four events; fouls received on the attempt mark and-ones; a block by the defence right after a miss
marks it blocked. Possession start is taken as the opponent's make or last free throw, the club's own defensive or
offensive rebound or steal, or the opponent's turnover, and the seconds from there to the shot are a coarse
shot-clock proxy (early 0 to 6 s, mid 7 to 17 s, late 18 s and over). The page uses these for the assisted filter, the
assisted share per zone, the timing table and the tooltip. Role metrics (usage, assist, turnover and rebound rates)
come from the box score with both teams' totals; on/off is the team's net rating with the player on court minus off,
shrunk toward zero with 1,500 minutes of prior weight and shown as descriptive, because half a season of on/off is
noisy. The defence-adjusted expectation adds each defending club's shrunk residual by zone to the context-only xFG.
Not in any feed, and therefore not on the page: defender distance, the real shot clock, dribbles, screens and play
types.

## Shot quality vs shooting skill

With a context-only expectation for every shot (the same shot taken by a league-average shooter), a player's
scoring splits into shot quality (expected points per attempt on the shots he takes) and shooting skill
(what he scores on top of that, per attempt). Both are noisy over a few games, so `model/profile.py` shrinks
them toward the league with empirical-Bayes weights estimated from 2025-26 by variance decomposition:
skill needs 263 attempts before a player's own record outweighs the prior (between-player spread 7 points per
100 attempts), shot quality only 10 (it is a stable trait of role and position). Split-half validation on
197 players: shrinking first-half skill cuts the error in predicting the second half from 0.153 to 0.128
points per attempt, and beats predicting zero for everyone (0.135). The page shows both figures with
percentiles against last season's players and a season curve of the skill estimate with its ±1 sd band.

A first version measured skill against the shooter-aware xFG and found zero between-player variance, which is
what should happen when the expectation already contains the shooter; quality and skill must be measured
against the context-only expectation.

## Scouting notes (Claude, validated)

`model/notes.py` writes a two-to-three-sentence note per player each night. Input is a fact sheet built from
the warehouse and the model outputs (season line, shooting splits, zone accuracy, xFG and points above
expectation, shot quality and skill with percentiles, last game); the prompt allows only those numbers, no
speculation, no other players, and the response is constrained to a JSON schema. Before a note is stored it
passes deterministic checks (`model/notes_checks.py`): every number cited traces to the fact sheet at its own
precision (rates may be written as percentages), length within bounds, no banned vocabulary (injuries,
contracts, character), no other player named. A failing note is retried once and otherwise rejected and not
shown. Only players whose fact sheet changed are regenerated, so a nightly run costs a few cents per changed
player. The page shows the note under the player's facts with its generation date and provenance.

`model/notes_eval.py` evaluates the generator on a fixed set of 30 fact sheets from 2025-26
(`model/notes_eval_set.jsonl`): automated pass rate, an LLM judge (separate prompt) scoring faithfulness and
usefulness 1-5 and listing unsupported claims, and agreement with human labels where the jsonl's `human_ok`
field has been filled in. `.github/workflows/notes-eval.yml` runs it on demand and commits
`model/notes_eval.json`. The offline validator tests are in `tests/test_notes.py`.

First evaluation (30 players, Claude Opus 5 as generator and judge): judge faithfulness 4.97/5 with one
unsupported claim in 30 notes (a league-wide superlative built from a 95th-percentile figure), usefulness 4.1/5.
The automated check initially rejected 47%, almost all false alarms from its own strictness (deficits written as
magnitudes, numbers inside string facts such as "5/12"); once fixed it passes 28 of 30, rejecting exactly the
two superlative notes, and the prompt now forbids league-wide claims.

## Monitoring

[`monitor.html`](https://baranerdogan11.github.io/Euroleague-Player-Lab/monitor.html) is the system's status page,
fed by `teams/E2026/monitor.json` which `model/monitor.py` writes at the end of every nightly run (and an append-only
`warehouse/E2026/run_history.jsonl`). It shows: pipeline result and run history; data freshness against the
schedule (games played per round, days since the last game); the xFG model's log loss and Brier per round on
this season's shots against a constant baseline and the training season, plus predicted versus actual make rate
and season-to-date calibration by decile; shooter-effect coverage; scouting-note acceptance and the latest
evaluation scores; the serving API's reachability, latency and served model hash checked against the registry.
Orange crossing grey on the calibration chart is the retrain signal.

## xFG as a service

`service/app.py` serves the deployed model with FastAPI:

- `POST /predict`: up to 500 shots per call, each validated (coordinates inside the court, 2 or 3 points,
  clock within a period); returns xFG, the context-only xFG for a league-average shooter, expected points and
  distance per shot, plus the model version in the body and in an `x-model-version` header. An optional league
  player code applies the shooter effect when the player is known.
- `GET /health`: liveness, model version and file hash. `GET /model`: model card and registry entry.
- Every request is logged as one JSON line (request id, path, status, latency, batch size, model version);
  set `LOG_FILE` to also append to a file.

`model/registry.json` records each trained model with its SHA-256, the SHA-256 of the training shots, metrics,
features and stage (`production`, `candidate`, `archived`); `python model/register.py --activate` promotes the
current model. The service reports which registry entry it is running.

`tests/test_service.py` holds 14 contract tests (schema validation, monotonic sanity checks, version headers,
shooter effect direction on average) and runs in both workflows. `.github/workflows/service.yml` runs them,
builds the Docker image, publishes it to GitHub Container Registry as
`ghcr.io/baranerdogan11/euroleague-xfg:latest` (and one tag per commit), then starts the published image and
calls `/predict` as a smoke test. `render.yaml` deploys the same image to Render's free tier with a health check.

The service is deployed at https://euroleague-xfg.onrender.com (free tier: the first call after idle takes
about 30 seconds); interactive docs at https://euroleague-xfg.onrender.com/docs.

```bash
curl -X POST https://euroleague-xfg.onrender.com/predict -H 'content-type: application/json' -d '{"shots":[{"x":0,"y":700,"pts":3}]}'
docker run -p 8000:8000 ghcr.io/baranerdogan11/euroleague-xfg:latest
curl -X POST localhost:8000/predict -H 'content-type: application/json' \
     -d '{"shots":[{"x":0,"y":700,"pts":3},{"x":10,"y":50,"pts":2,"minute":38,"clock":"00:20","home":false,"margin":-3,"player":"002100"}]}'
```

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

- `index.html`: the page (loads a club's JSON when it is selected); `monitor.html`: the status page

### League leaderboards

Four boards, points, rebounds and assists a game and three-point percentage, are precomputed in `build.py`
(`leaderboards()`) and inlined in `index.json` as `leaders`, about 600 bytes. Rows carry only a player id plus
the raw totals; the page joins names, clubs and photos from `roster`, whose entries also carry each player's
rank on every board so the viewed player can be pinned under the top ten.

Qualification is pro-rated off the player's own club's played games rather than fixed at a games count, the
way the NBA pro-rates its 70%-of-games rule in season, so the qualifying pool stays flat as the season grows
instead of tripling: a player needs appearances in 70% of his club's games and 10 minutes a game. The
three-point board is gated on attempts alone, `max(15, 2 x rounds)`, and ranked on the raw percentage. The
floor of 15 is the same attempt minimum the rest of the file already requires before it will print a 3P%.
Before anyone can reach that gate, the board drops to the highest attempt count that still fields ten shooters
(never under 5) and says so on the page; the relaxed gate lifts itself back to 15 within a few rounds.
Empirical-Bayes shrinkage was measured on 2025-26 and rejected: at the season-end gate it compresses 23.9
points of spread to 4.8, so every row would round to the same number.
- `p/<pid>.html`: one share stub per player with his Open Graph card (name, club, photo), forwarding to his page; written by `build.py`, handed out by the page's Copy link button
- `teams/E2026/index.json`, `teams/E2026/<CLUB>.json`: compact per-club data (stats, game log, shots)
- `photos/<player>.webp`, `logos/<CLUB>.png`: media-day photos and crests
- `warehouse/E2026/*.parquet`: the queryable season warehouse (schema in `warehouse/SCHEMA.md`)
- `fetch_season.py`, `checks.py`, `warehouse.py`, `warehouse_tests.py`, `build.py`, `template.html`: the pipeline and page source

The page fetches its data files, so serve the folder over HTTP to run it locally
(`python -m http.server 8000`, then open http://localhost:8000/); opening `index.html` directly from disk will not load data.

## Data

Rosters, crests, photos, box scores and shot coordinates come from the Euroleague official API and live feeds.
Coordinates are in centimetres relative to the basket; the court is drawn to FIBA dimensions.
