"""Build the site: index.html from template.html, plus one compact JSON per club under teams/<season>/.

Photos (photos/*.webp) and crests (logos/*.png) are referenced by path, not embedded, so the page stays
small and each club's data loads when it is selected. If data/<previous season>/ exists, every current
player also carries his previous-season games and shots (from whichever club he played for), so profiles
are populated before the current season's games. Run after fetch_season.py.

usage: python build.py E2026
"""
import datetime
import glob
import json
import os
import sys

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2026"
PREV = f"E{int(SEASON[1:]) - 1}"
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", SEASON)
PREV_DATA = os.path.join(ROOT, "data", PREV)
OUT = os.path.join(ROOT, "teams", SEASON)
os.makedirs(OUT, exist_ok=True)
STAT_KEYS = ["pts", "fgm2", "fga2", "fgm3", "fga3", "ftm", "fta", "oreb", "dreb", "reb", "ast", "stl", "tov", "blk", "blka", "pf", "fd", "pir"]
label = lambda s: f"{s[1:]}-{str(int(s[1:]) + 1)[2:]}"


def minutes(s):
    if not s or ":" not in str(s):
        return 0.0
    m, sec = str(s).split(":")
    return int(m) + int(sec) / 60


def gkey(g):
    return (g["date"], g["code"])


def player_season(pid, box, shots, games_by_code, own_by_game):
    """Season totals, per-game log and compact shots for one player; game index is local to this player."""
    lines = sorted([b for b in box if b["pid"] == pid and minutes(b["min"]) > 0], key=lambda b: gkey(games_by_code[b["game"]]))
    if not lines:
        return None
    codes = [b["game"] for b in lines]
    gidx = {c: i for i, c in enumerate(codes)}
    tot = {k: sum(b[k] for b in lines) for k in STAT_KEYS}
    tot["min"] = round(sum(minutes(b["min"]) for b in lines), 1)
    tot["gp"] = len(lines)
    log = [[gidx[b["game"]], round(minutes(b["min"]), 1), b["pts"], b["reb"], b["ast"], b["stl"], b["blk"], b["tov"], b["fgm2"], b["fga2"], b["fgm3"], b["fga3"], b["ftm"], b["fta"], b["pir"], b["plusminus"]] for b in lines]
    sh = [[gidx[s["game"]], s["x"], s["y"], 1 if s["made"] else 0, s["pts"], s["q"], s["zone"], 1 if s["fastbreak"] else 0, 1 if s["second_chance"] else 0]
          for s in sorted([s for s in shots if s["pid"] == pid and s["game"] in gidx], key=lambda s: (gidx[s["game"]], s["q"], s["clock"]))]
    games = [dict(games_by_code[c], own=own_by_game[c]) for c in codes]
    return {"tot": tot, "log": log, "shots": sh, "games": games}


# ---- previous season, pooled across clubs (players move)
prev_box, prev_shots, prev_games, prev_own = [], [], {}, {}
if os.path.isdir(PREV_DATA):
    for path in glob.glob(os.path.join(PREV_DATA, "*.json")):
        if path.endswith("clubs.json"):
            continue
        d = json.load(open(path))
        for g in d["games"]:
            prev_games[g["code"]] = g
        for b in d["box"]:
            prev_box.append(b); prev_own[(b["pid"], b["game"])] = d["club"]
        prev_shots.extend(d["shots"])
    print(f"previous season {PREV}: {len(prev_games)} games, {len(prev_box)} box lines, {len(prev_shots)} shots pooled")

clubs = json.load(open(os.path.join(DATA, "clubs.json")))
club_list = list(clubs["clubs"])
summary = []
for path in sorted(glob.glob(os.path.join(DATA, "*.json"))):
    if path.endswith("clubs.json"):
        continue
    d = json.load(open(path))
    if d.get("club_meta"):
        club_list = [c for c in club_list if c["code"] != d["club"]] + [dict(d["club_meta"], demo=True)]
    games_by_code = {g["code"]: g for g in d["games"]}
    own = {g["code"]: d["club"] for g in d["games"]}
    players = []
    n_prev = 0
    for p in sorted(d["players"], key=lambda p: (int(p["dorsal"]) if str(p["dorsal"]).isdigit() else 99, p["name"])):
        cur = player_season(p["pid"], d["box"], d["shots"], games_by_code, own) or {"tot": {**{k: 0 for k in STAT_KEYS}, "min": 0, "gp": 0}, "log": [], "shots": [], "games": []}
        rec = {"pid": p["pid"], "name": p["name"], "dorsal": p["dorsal"], "position": p["position"], "height": p["height"], "birth": p["birth"],
               "country": p["country"], "photo": p["photo"], "cur": cur}
        if prev_games:
            pv = player_season(p["pid"], prev_box, prev_shots, prev_games, {g: c for (pid, g), c in prev_own.items() if pid == p["pid"]})
            if pv:
                rec["prev"] = pv; n_prev += 1
        players.append(rec)
    team = {"code": d["club"], "season": SEASON, "label": label(SEASON), "prev_label": label(PREV) if prev_games else None,
            "games_played": len(d["games"]), "upcoming": d.get("upcoming", []), "players": players,
            "real_code": (d.get("club_meta") or {}).get("real_code", d["club"])}
    json.dump(team, open(os.path.join(OUT, f"{d['club']}.json"), "w"), separators=(",", ":"), ensure_ascii=False)
    summary.append((d["club"], len(players), n_prev, len(d["games"]), len(d["shots"])))

meta = {"season": SEASON, "label": label(SEASON), "prev_label": label(PREV) if prev_games else None, "clubs": club_list,
        "built": datetime.date.today().isoformat(), "path": f"teams/{SEASON}/"}
json.dump(meta, open(os.path.join(OUT, "index.json"), "w"), ensure_ascii=False)
tpl = open(os.path.join(ROOT, "template.html"), encoding="utf-8").read()
open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(tpl.replace("/*META*/", json.dumps(meta, ensure_ascii=False)))
for s in summary:
    print("%-4s players %2d  with %s data %2d  games %2d  shots %4d" % (s[0], s[1], label(PREV), s[2], s[3], s[4]))
print("index.html + teams/%s/*.json written" % SEASON)
