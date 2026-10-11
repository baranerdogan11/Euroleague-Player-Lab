"""Lineup layer: who was on the floor for every second of every game, from the box-score starters and the
substitution events, and what happened while they were there.

Reads the warehouse (box, games, events) and writes two Parquet tables:
  stints    one row per club per stretch of play with an unchanged five (game, club, stint): the five players,
            seconds, and both clubs' points, field-goal attempts, offensive rebounds, turnovers and free-throw
            attempts during the stretch (possessions = FGA - OREB + TOV + 0.44 FTA, the same estimate the site
            uses for pace)
  oncourt   one row per player per game: seconds on court from the reconstruction, next to the box-score minutes

Validation: every club has exactly five on the floor at every event, and each player's reconstructed seconds
agree with the box score to within a minute (a scorer's clock and a stat sheet never agree to the second).

usage: python lineups.py E2026
"""
import json
import os
import sys
import duckdb

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2026"
ROOT = os.path.dirname(os.path.abspath(__file__))
W = os.path.join(ROOT, "warehouse", SEASON)
con = duckdb.connect()
for t in ["box", "games", "events"]:
    con.execute(f"create view {t} as select * from read_parquet('{os.path.join(W, t + '.parquet')}')")
rows = lambda q: [dict(zip([d[0] for d in con.description], r)) for r in con.execute(q).fetchall()]

POINTS = {"2FGM": 2, "3FGM": 3, "FTM": 1}
FGA = {"2FGA", "2FGM", "3FGA", "3FGM"}
PERIOD_SEC = lambda per: 300 if per >= 5 else 600
starters = {}
for r in rows("select game, club, player from box where starter"):
    starters.setdefault((r["game"], r["club"]), set()).add(r["player"])
box_min = {(r["game"], r["player"]): (r["club"], r["minutes"] or 0.0) for r in rows("select game, player, club, minutes from box")}
games = {g["game"]: (g["home"], g["away"]) for g in rows("select game, home, away from games where played")}

stints, oncourt, problems = [], [], []
by_game = {}
for e in rows("select * from events order by game, seq"):
    by_game.setdefault(e["game"], []).append(e)

def chronological(evs):
    """The feed's sequence numbers are not the order of play: a corrected or late-entered play keeps the clock it happened
    at but gets the next number. Order by period and clock instead, with the sequence breaking ties; an event without a
    clock (period markers, timeouts) takes the clock of the event entered before it."""
    out, last = [], None
    for e in evs:
        if e["playtype"] == "BP":
            cs = PERIOD_SEC(e["period"])
        elif e["playtype"] in ("EP", "EG"):
            cs = 0
        elif e["clock_sec"] is not None:
            cs = e["clock_sec"]
        else:
            cs = last if last is not None else PERIOD_SEC(e["period"])
        last = cs if e["playtype"] not in ("EP", "EG") else None
        out.append((e["period"], -cs, e["seq"], e))
    out.sort(key=lambda x: x[:3])
    return [x[3] for x in out]


for gc, evs in by_game.items():
    if gc not in games:
        continue
    evs = chronological(evs)
    home, away = games[gc]
    on = {c: set(starters.get((gc, c), set())) for c in (home, away)}
    if any(len(v) != 5 for v in on.values()):
        problems.append(f"game {gc}: starters {[len(v) for v in on.values()]}"); continue
    secs = {}                                     # (player) -> seconds on court
    cur = {c: {"pts": 0, "fga": 0, "oreb": 0, "tov": 0, "fta": 0} for c in (home, away)}
    sec = 0                                       # seconds played in the current stint
    per, clock = 1, 600                           # current period and last known clock (seconds remaining)
    idx = {c: 0 for c in (home, away)}

    def flush():
        """Close the current stint for both clubs if any time or any possession passed."""
        global sec
        if sec <= 0 and all(v["fga"] + v["tov"] + v["fta"] == 0 for v in cur.values()):
            return
        for c in (home, away):
            o = away if c == home else home
            stints.append({"game": gc, "club": c, "stint": idx[c], "players": sorted(on[c]), "sec": sec, "pts": cur[c]["pts"], "opp_pts": cur[o]["pts"],
                           "fga": cur[c]["fga"], "oreb": cur[c]["oreb"], "tov": cur[c]["tov"], "fta": cur[c]["fta"],
                           "opp_fga": cur[o]["fga"], "opp_oreb": cur[o]["oreb"], "opp_tov": cur[o]["tov"], "opp_fta": cur[o]["fta"]})
            idx[c] += 1
            for p in on[c]:
                secs[p] = secs.get(p, 0) + sec
        sec = 0
        for v in cur.values():
            for k in v:
                v[k] = 0

    def advance(to_per, to_clock):
        """Move the game clock forward to (period, seconds remaining), crediting the elapsed time to the current five."""
        global per, clock, sec
        if to_per > per:                          # the rest of the old period, then full periods in between
            sec += clock
            for p in range(per + 1, to_per):
                sec += PERIOD_SEC(p)
            per, clock = to_per, PERIOD_SEC(to_per)
        if to_clock is not None and to_clock < clock:
            sec += clock - to_clock
            clock = to_clock

    for e in evs:
        pt, club, pl = e["playtype"], e["club"], e["player"]
        if pt == "BP":
            advance(e["period"], None); continue
        if pt == "EP" or pt == "EG":
            advance(e["period"], 0); continue
        if e["clock_sec"] is not None:
            advance(e["period"], e["clock_sec"])
        if pt in ("IN", "OUT") and club in on and pl:
            flush()
            if pt == "IN":
                on[club].add(pl)
            else:
                on[club].discard(pl)
            continue
        if club not in cur:
            continue
        if any(len(v) != 5 for v in on.values()) and pt in FGA | {"TO", "FTA", "FTM"}:
            problems.append(f"game {gc} seq {e['seq']}: {[len(v) for v in on.values()]} on court")
        cur[club]["pts"] += POINTS.get(pt, 0)
        if pt in FGA:
            cur[club]["fga"] += 1
        elif pt == "O":
            cur[club]["oreb"] += 1
        elif pt == "TO":
            cur[club]["tov"] += 1
        elif pt in ("FTA", "FTM"):
            cur[club]["fta"] += 1
    flush()
    for (g, p), (c, m) in box_min.items():
        if g == gc:
            oncourt.append({"game": gc, "player": p, "club": c, "sec": secs.get(p, 0), "box_min": m})

bad = [o for o in oncourt if abs(o["sec"] / 60 - o["box_min"]) > 1.0]
for o in bad[:10]:
    problems.append(f"game {o['game']} {o['player']}: reconstructed {o['sec'] / 60:.1f} min, box {o['box_min']}")


def to_parquet(name, rs, schema):
    tmp = os.path.join(W, f"{name}.jsonl")
    with open(tmp, "w") as f:
        for r in rs:
            f.write(json.dumps({k: r.get(k) for k, _ in schema}) + "\n")
    cols = ", ".join(f"'{k}': '{t}'" for k, t in schema)
    con.execute(f"copy (select * from read_json('{tmp}', format='newline_delimited', columns={{{cols}}})) to '{os.path.join(W, name + '.parquet')}' (format parquet, compression zstd)")
    os.remove(tmp)
    return len(rs)


n_st = to_parquet("stints", stints, [("game", "INTEGER"), ("club", "VARCHAR"), ("stint", "INTEGER"), ("players", "VARCHAR[]"), ("sec", "INTEGER"), ("pts", "INTEGER"), ("opp_pts", "INTEGER"),
                                     ("fga", "INTEGER"), ("oreb", "INTEGER"), ("tov", "INTEGER"), ("fta", "INTEGER"), ("opp_fga", "INTEGER"), ("opp_oreb", "INTEGER"), ("opp_tov", "INTEGER"), ("opp_fta", "INTEGER")])
n_on = to_parquet("oncourt", oncourt, [("game", "INTEGER"), ("player", "VARCHAR"), ("club", "VARCHAR"), ("sec", "INTEGER"), ("box_min", "DOUBLE")])
manifest_path = os.path.join(W, "manifest.json")
manifest = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {"season": SEASON, "tables": {}}
manifest["tables"].update({"stints": n_st, "oncourt": n_on})
json.dump(manifest, open(manifest_path, "w"), indent=1)
for p in problems[:20]:
    print("WARN", p)
print(f"{SEASON}: {len(by_game)} games, {n_st} stints, {n_on} player-games; {len(bad)} player-games off the box score by more than a minute")
