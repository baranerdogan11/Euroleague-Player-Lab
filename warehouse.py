"""Silver layer: normalised tables built from the cached feeds (bronze) and persisted as Parquet.

Tables under warehouse/<season>/: clubs, players, roster_stints, games, box, shots. Player codes are the
league's six-digit person codes everywhere (the play-by-play feed prefixes them with "P"; that is stripped).
Roster stints carry the league's own start and end dates, so a player who changes club mid-season has two
rows and his shots stay attributed to the club he played for in each game.

usage: python warehouse.py E2026
"""
import glob
import json
import os
import sys
import duckdb

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2026"
ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache", SEASON)
OUT = os.path.join(ROOT, "warehouse", SEASON)
os.makedirs(OUT, exist_ok=True)


def load(name):
    j = json.load(open(os.path.join(CACHE, name)))
    return j["data"] if isinstance(j, dict) and "data" in j else j


def norm_pid(s):
    s = (s or "").strip()
    return s[1:] if s.startswith("P") else s


def date_only(s):
    return (s or "")[:10] or None


# ---- clubs
clubs = [{"club": c["code"], "name": c["name"], "short": c.get("abbreviatedName") or c["name"], "country": (c.get("country") or {}).get("name"), "city": c.get("city")}
         for c in load("clubs.json")]
club_codes = {c["club"] for c in clubs}

# ---- players and roster stints (one row per person per club registration)
players, stints = {}, []
for c in clubs:
    path = os.path.join(CACHE, f"roster_{c['club']}.json")
    if not os.path.exists(path):
        continue
    for p in load(os.path.basename(path)):
        if p.get("type") != "J":
            continue
        pc = p["person"]["code"]
        players[pc] = {"player": pc, "name": p["person"]["name"], "birth_date": date_only(p["person"].get("birthDate")),
                       "country": (p["person"].get("country") or {}).get("name"), "height_cm": p["person"].get("height") or None}
        stints.append({"player": pc, "club": c["club"], "start_date": date_only(p.get("startDate")), "end_date": date_only(p.get("endDate")),
                       "active": bool(p.get("active")), "dorsal": p.get("dorsal") or None, "position": p.get("positionName"), "last_team": p.get("lastTeam") or None})

# ---- games (full schedule, played flag)
games = []
for g in load("games_latest.json"):
    hs, as_ = g["home"]["score"], g["away"]["score"]
    games.append({"game": g["code"], "round": g["round"]["round"], "phase": g["phaseType"]["code"], "date_utc": g["date"],
                  "date": date_only(g["date"]), "home": g["home"]["code"], "away": g["away"]["code"], "home_score": hs, "away_score": as_,
                  "played": (hs or 0) + (as_ or 0) > 0, "status": g.get("status")})
game_teams = {g["game"]: (g["home"], g["away"]) for g in games}

# ---- box score lines and shots, both teams of every cached game
box, shots = [], []
for path in sorted(glob.glob(os.path.join(CACHE, "box_*.json"))):
    gc = int(os.path.basename(path)[4:-5])
    for side in json.load(open(path)).get("Stats", []):
        for p in side.get("PlayersStats", []):
            club = p.get("Team", "").strip()
            m = p.get("Minutes") or "0:00"
            mm, ss = (m.split(":") + ["0"])[:2] if ":" in m else ("0", "0")
            box.append({"game": gc, "player": norm_pid(p["Player_ID"]), "club": club, "player_name": p["Player"].strip(), "starter": bool(p.get("IsStarter")),
                        "minutes": round(int(mm) + int(ss) / 60, 2), "pts": p["Points"], "fgm2": p["FieldGoalsMade2"], "fga2": p["FieldGoalsAttempted2"],
                        "fgm3": p["FieldGoalsMade3"], "fga3": p["FieldGoalsAttempted3"], "ftm": p["FreeThrowsMade"], "fta": p["FreeThrowsAttempted"],
                        "oreb": p["OffensiveRebounds"], "dreb": p["DefensiveRebounds"], "reb": p["TotalRebounds"], "ast": p["Assistances"],
                        "stl": p["Steals"], "tov": p["Turnovers"], "blk": p["BlocksFavour"], "blka": p["BlocksAgainst"], "pf": p["FoulsCommited"],
                        "fd": p["FoulsReceived"], "pir": p["Valuation"], "plusminus": p.get("Plusminus")})
for path in sorted(glob.glob(os.path.join(CACHE, "points_*.json"))):
    gc = int(os.path.basename(path)[7:-5])
    pts = json.load(open(path)); pts = pts.get("Rows", []) if isinstance(pts, dict) else pts   # cached as a bare row list; fixtures hold the full response
    for i, r in enumerate(pts):
        act = r["ID_ACTION"].strip()
        if act not in ("2FGM", "2FGA", "3FGM", "3FGA"):
            continue
        shots.append({"game": gc, "seq": r.get("NUM_ANOT", i), "player": norm_pid(r["ID_PLAYER"]), "club": r["TEAM"].strip(), "x": r["COORD_X"], "y": r["COORD_Y"],
                      "made": act.endswith("M"), "pts": 3 if act.startswith("3") else 2, "zone": r["ZONE"].strip(), "minute": r["MINUTE"], "clock": r["CONSOLE"],
                      "fastbreak": r["FASTBREAK"] == "1", "second_chance": r["SECOND_CHANCE"] == "1", "points_off_tov": r.get("POINTS_OFF_TURNOVER") == "1",
                      "score_home": r.get("POINTS_A"), "score_away": r.get("POINTS_B")})
# players who appear in box scores but not in any current roster feed (departed before the first roster pull)
for b in box:
    players.setdefault(b["player"], {"player": b["player"], "name": b["player_name"], "birth_date": None, "country": None, "height_cm": None})

con = duckdb.connect()


def to_parquet(name, rows, schema):
    """schema: list of (column, duckdb type); rows: list of dicts."""
    tmp = os.path.join(OUT, f"{name}.jsonl")
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps({k: r.get(k) for k, _ in schema}) + "\n")
    cols = ", ".join(f"'{k}': '{t}'" for k, t in schema)
    con.execute(f"copy (select * from read_json('{tmp}', format='newline_delimited', columns={{{cols}}})) to '{os.path.join(OUT, name + '.parquet')}' (format parquet, compression zstd)")
    os.remove(tmp)
    return len(rows)

counts = {
    "clubs": to_parquet("clubs", clubs, [("club", "VARCHAR"), ("name", "VARCHAR"), ("short", "VARCHAR"), ("country", "VARCHAR"), ("city", "VARCHAR")]),
    "players": to_parquet("players", list(players.values()), [("player", "VARCHAR"), ("name", "VARCHAR"), ("birth_date", "DATE"), ("country", "VARCHAR"), ("height_cm", "INTEGER")]),
    "roster_stints": to_parquet("roster_stints", stints, [("player", "VARCHAR"), ("club", "VARCHAR"), ("start_date", "DATE"), ("end_date", "DATE"), ("active", "BOOLEAN"), ("dorsal", "VARCHAR"), ("position", "VARCHAR"), ("last_team", "VARCHAR")]),
    "games": to_parquet("games", games, [("game", "INTEGER"), ("round", "INTEGER"), ("phase", "VARCHAR"), ("date_utc", "TIMESTAMP"), ("date", "DATE"), ("home", "VARCHAR"), ("away", "VARCHAR"), ("home_score", "INTEGER"), ("away_score", "INTEGER"), ("played", "BOOLEAN"), ("status", "VARCHAR")]),
    "box": to_parquet("box", box, [("game", "INTEGER"), ("player", "VARCHAR"), ("club", "VARCHAR"), ("starter", "BOOLEAN"), ("minutes", "DOUBLE"), ("pts", "INTEGER"), ("fgm2", "INTEGER"), ("fga2", "INTEGER"), ("fgm3", "INTEGER"), ("fga3", "INTEGER"), ("ftm", "INTEGER"), ("fta", "INTEGER"), ("oreb", "INTEGER"), ("dreb", "INTEGER"), ("reb", "INTEGER"), ("ast", "INTEGER"), ("stl", "INTEGER"), ("tov", "INTEGER"), ("blk", "INTEGER"), ("blka", "INTEGER"), ("pf", "INTEGER"), ("fd", "INTEGER"), ("pir", "INTEGER"), ("plusminus", "INTEGER")]),
    "shots": to_parquet("shots", shots, [("game", "INTEGER"), ("seq", "INTEGER"), ("player", "VARCHAR"), ("club", "VARCHAR"), ("x", "INTEGER"), ("y", "INTEGER"), ("made", "BOOLEAN"), ("pts", "INTEGER"), ("zone", "VARCHAR"), ("minute", "INTEGER"), ("clock", "VARCHAR"), ("fastbreak", "BOOLEAN"), ("second_chance", "BOOLEAN"), ("points_off_tov", "BOOLEAN"), ("score_home", "INTEGER"), ("score_away", "INTEGER")]),
}
json.dump({"season": SEASON, "tables": counts}, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)
print(f"{SEASON} warehouse: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
