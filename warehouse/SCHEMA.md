# Warehouse schema

One folder per season (`warehouse/E2026/`), six Parquet tables, queried with DuckDB. Bronze is the cached
feed JSON under `cache/<season>/`; silver is this folder (built by `warehouse.py`); gold is `teams/<season>/`
(built by `build.py` with SQL over silver). `warehouse_tests.py` asserts the invariants below on every run.

Player codes are the league's six-digit person codes (`002100`); the play-by-play feed's `P` prefix is removed.
Club codes are the league's three-letter codes (`ULK`, `OLY`). Coordinates are centimetres relative to the
basket, `x` lateral, `y` toward half court.

| Table | Grain | Key | Columns |
|---|---|---|---|
| `clubs` | one row per club | `club` | `name`, `short`, `country`, `city` |
| `players` | one row per person seen this season | `player` | `name`, `birth_date`, `country`, `height_cm` |
| `roster_stints` | one row per registration of a player with a club | (`player`, `club`, `start_date`) | `end_date`, `active`, `dorsal`, `position`, `last_team` |
| `games` | one row per scheduled game | `game` | `round`, `phase`, `date_utc`, `date`, `home`, `away`, `home_score`, `away_score`, `played`, `status` |
| `box` | one row per player per played game | (`game`, `player`) | `club`, `starter`, `minutes`, `pts`, `fgm2`, `fga2`, `fgm3`, `fga3`, `ftm`, `fta`, `oreb`, `dreb`, `reb`, `ast`, `stl`, `tov`, `blk`, `blka`, `pf`, `fd`, `pir`, `plusminus` |
| `shots` | one row per field-goal attempt | (`game`, `seq`) | `player`, `club`, `x`, `y`, `made`, `pts`, `zone`, `minute`, `clock`, `fastbreak`, `second_chance`, `points_off_tov`, `score_home`, `score_away` |

## Invariants (all enforced)

- `clubs`: exactly 20, unique codes. `players`: unique codes, non-empty names.
- `roster_stints`: player and club exist; `start_date <= end_date`; at most one active stint per player; every club has 10 to 22 active players. A player who moves mid-season has two stints and keeps one `player` code.
- `games`: unique codes; both clubs exist; `played` is true exactly when a score exists; no played game in the future; every club has 38 regular-season games.
- `box`: game exists and was played; club is one of the game's two; one line per player per game; makes never exceed attempts; `pts = 2*fgm2 + 3*fgm3 + ftm`.
- `shots`: game exists and was played; club is one of the game's two; coordinates inside the court; per player per game, attempts and makes reconcile exactly with the box score; every shooter has a box line.

## Querying

```python
import duckdb
con = duckdb.connect()
con.execute("create view shots as select * from 'warehouse/E2026/shots.parquet'")
con.execute("create view players as select * from 'warehouse/E2026/players.parquet'")
print(con.sql("""
  select p.name, count(*) att, round(100.0 * avg(made::int), 1) fg_pct
  from shots s join players p using (player)
  where s.pts = 3 and y < 141.5          -- corner threes
  group by 1 having att >= 20 order by fg_pct desc limit 10"""))
```

Any tool that reads Parquet (pandas, polars, R arrow, Power BI, Tableau) can open these files directly.
