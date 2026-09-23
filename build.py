"""Build the site: index.html from template.html, plus one compact JSON per club under teams/<season>/.

Photos (photos/*.webp) and crests (logos/*.png) are referenced by path, not embedded, so the page stays
small and each club's data loads when it is selected. Run after fetch_season.py.

usage: python build.py E2026
"""
import glob
import json
import os
import sys

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2026"
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", SEASON)
OUT = os.path.join(ROOT, "teams", SEASON)
os.makedirs(OUT, exist_ok=True)
STAT_KEYS = ["pts", "fgm2", "fga2", "fgm3", "fga3", "ftm", "fta", "oreb", "dreb", "reb", "ast", "stl", "tov", "blk", "blka", "pf", "fd", "pir"]


def minutes(s):
    if not s or ":" not in str(s):
        return 0.0
    m, sec = str(s).split(":")
    return int(m) + int(sec) / 60


clubs = json.load(open(os.path.join(DATA, "clubs.json")))
summary = []
for path in sorted(glob.glob(os.path.join(DATA, "*.json"))):
    if path.endswith("clubs.json"):
        continue
    d = json.load(open(path))
    order = [g["code"] for g in sorted(d["games"], key=lambda g: (g["date"], g["code"]))]
    gidx = {c: i for i, c in enumerate(order)}
    players, pidx = [], {}
    for p in sorted(d["players"], key=lambda p: (int(p["dorsal"]) if str(p["dorsal"]).isdigit() else 99, p["name"])):
        lines = [b for b in d["box"] if b["pid"] == p["pid"] and minutes(b["min"]) > 0]
        tot = {k: sum(b[k] for b in lines) for k in STAT_KEYS}
        tot["min"] = round(sum(minutes(b["min"]) for b in lines), 1)
        tot["gp"] = len(lines)
        log = [[gidx[b["game"]], round(minutes(b["min"]), 1), b["pts"], b["reb"], b["ast"], b["stl"], b["blk"], b["tov"], b["fgm2"], b["fga2"], b["fgm3"], b["fga3"], b["ftm"], b["fta"], b["pir"], b["plusminus"]]
               for b in sorted(lines, key=lambda b: gidx[b["game"]])]
        pidx[p["pid"]] = len(players)
        players.append({"pid": p["pid"], "name": p["name"], "dorsal": p["dorsal"], "position": p["position"], "height": p["height"],
                        "birth": p["birth"], "country": p["country"], "photo": p["photo"], "tot": tot, "log": log})
    shots = [[gidx[s["game"]], pidx[s["pid"]], s["x"], s["y"], 1 if s["made"] else 0, s["pts"], s["q"], s["zone"], 1 if s["fastbreak"] else 0, 1 if s["second_chance"] else 0]
             for s in sorted(d["shots"], key=lambda s: (gidx[s["game"]], s["q"], s["clock"])) if s["pid"] in pidx]
    team = {"code": d["club"], "season": SEASON, "games": [g for g in sorted(d["games"], key=lambda g: (g["date"], g["code"]))],
            "upcoming": d.get("upcoming", []), "players": players, "shots": shots}
    json.dump(team, open(os.path.join(OUT, f"{d['club']}.json"), "w"), separators=(",", ":"), ensure_ascii=False)
    summary.append((d["club"], len(players), len(order), len(shots)))

meta = {"season": SEASON, "label": SEASON.replace("E", "").replace(SEASON[1:], f"{SEASON[1:]}-{str(int(SEASON[1:]) + 1)[2:]}"),
        "clubs": clubs["clubs"], "built": __import__("datetime").date.today().isoformat(), "path": f"teams/{SEASON}/"}
json.dump(meta, open(os.path.join(OUT, "index.json"), "w"), ensure_ascii=False)
tpl = open(os.path.join(ROOT, "template.html"), encoding="utf-8").read()
open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(tpl.replace("/*META*/", json.dumps(meta, ensure_ascii=False)))
for s in summary:
    print("%-4s players %2d  games %2d  shots %4d" % s)
print("index.html + teams/%s/*.json written" % SEASON)
