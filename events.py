"""Play-by-play layer: every event of every played game, and the context of every shot derived from it.

Reads cache/<season>/pbp_<game>.json (the live API's PlayByPlay feed, fetched by fetch_season.py) and writes two
Parquet tables next to the rest of the warehouse:
  events        one row per play-by-play event (game, seq), sequence numbers shared with the shots table
  shot_context  one row per shot: assisted (makes only), fouled on the shot, blocked (misses only), and seconds
                since the possession started, from the scorer's clock (a coarse shot-clock proxy)

usage: python events.py E2026
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
PERIODS = [("FirstQuarter", 1), ("SecondQuarter", 2), ("ThirdQuarter", 3), ("ForthQuarter", 4), ("ExtraTime", 5)]
FG = {"2FGA", "2FGM", "3FGA", "3FGM"}
norm_pid = lambda s: ((s or "").strip()[1:] if (s or "").strip().startswith("P") else (s or "").strip()) or None


def clock_sec(s):
    """'09:39' -> seconds remaining in the period, None when the feed has no clock."""
    if not s or ":" not in s:
        return None
    m, sec = s.split(":")[:2]
    try:
        return int(m) * 60 + int(sec)
    except ValueError:
        return None


events = []
for path in sorted(glob.glob(os.path.join(CACHE, "pbp_*.json"))):
    gc = int(os.path.basename(path)[4:-5])
    d = json.load(open(path))
    for key, per in PERIODS:
        for e in d.get(key) or []:
            events.append({"game": gc, "seq": e["NUMBEROFPLAY"], "period": per, "club": (e.get("CODETEAM") or "").strip() or None, "player": norm_pid(e.get("PLAYER_ID")),
                           "playtype": (e.get("PLAYTYPE") or "").strip(), "minute": e.get("MINUTE"), "clock": e.get("MARKERTIME") or None, "clock_sec": clock_sec(e.get("MARKERTIME")),
                           "score_home": e.get("POINTS_A"), "score_away": e.get("POINTS_B"), "info": e.get("PLAYINFO") or None})

# ---- per-shot context: walk each game's events in order
context = []
by_game = {}
for e in events:
    by_game.setdefault(e["game"], []).append(e)
for gc, evs in by_game.items():
    evs.sort(key=lambda e: e["seq"])
    clubs = [c for c in {e["club"] for e in evs} if c]
    start = {c: (1, 600) for c in clubs}          # possession start per club: (period, clock seconds remaining)
    for i, e in enumerate(evs):
        pt, club, per, cs = e["playtype"], e["club"], e["period"], e["clock_sec"]
        opp = next((c for c in clubs if c != club), None) if club else None
        if pt == "BP":
            for c in clubs:
                start[c] = (per, 300 if per >= 5 else 600)
        if pt in FG and club:
            made = pt.endswith("M")
            look = evs[i + 1:i + 5]
            assisted = int(any(x["playtype"] == "AS" and x["club"] == club for x in look if x["period"] == per)) if made else None
            fouled = int(any(x["playtype"] == "RV" and x["club"] == club and x["player"] == e["player"] for x in evs[i + 1:i + 4] if x["period"] == per))
            blocked = None if made else int(any(x["playtype"] == "FV" and x["club"] == opp for x in evs[i + 1:i + 3]))
            sp, sc = start.get(club, (per, None))
            poss = (sc - cs) if (cs is not None and sc is not None and sp == per) else None
            if poss is not None and (poss < 0 or poss > 40):
                poss = None
            context.append({"game": gc, "seq": e["seq"], "assisted": assisted, "fouled": fouled, "blocked": blocked, "poss_sec": poss})
            if made and opp:                      # the opponent starts a possession after a make (and after the last free throw of an and-one, handled by FTM below)
                start[opp] = (per, cs)
        elif club and cs is not None:
            if pt in ("FTM",) and opp:             # each made free throw restarts the opponent's clock; the last one stands
                start[opp] = (per, cs)
            elif pt == "D" or pt == "ST" or pt == "O":   # own defensive rebound, steal, or offensive rebound: fresh possession for this club
                start[club] = (per, cs)
            elif pt == "TO" and opp:              # turnover: the opponent starts
                start[opp] = (per, cs)

con = duckdb.connect()


def to_parquet(name, rows, schema):
    tmp = os.path.join(OUT, f"{name}.jsonl")
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps({k: r.get(k) for k, _ in schema}) + "\n")
    cols = ", ".join(f"'{k}': '{t}'" for k, t in schema)
    con.execute(f"copy (select * from read_json('{tmp}', format='newline_delimited', columns={{{cols}}})) to '{os.path.join(OUT, name + '.parquet')}' (format parquet, compression zstd)")
    os.remove(tmp)
    return len(rows)


os.makedirs(OUT, exist_ok=True)
n_ev = to_parquet("events", events, [("game", "INTEGER"), ("seq", "INTEGER"), ("period", "INTEGER"), ("club", "VARCHAR"), ("player", "VARCHAR"), ("playtype", "VARCHAR"), ("minute", "INTEGER"),
                                     ("clock", "VARCHAR"), ("clock_sec", "INTEGER"), ("score_home", "INTEGER"), ("score_away", "INTEGER"), ("info", "VARCHAR")])
n_ctx = to_parquet("shot_context", context, [("game", "INTEGER"), ("seq", "INTEGER"), ("assisted", "INTEGER"), ("fouled", "INTEGER"), ("blocked", "INTEGER"), ("poss_sec", "INTEGER")])
manifest_path = os.path.join(OUT, "manifest.json")
manifest = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {"season": SEASON, "tables": {}}
manifest["tables"].update({"events": n_ev, "shot_context": n_ctx})
json.dump(manifest, open(manifest_path, "w"), indent=1)
print(f"{SEASON}: {len(by_game)} games with play-by-play, {n_ev} events, {n_ctx} shots with context")
