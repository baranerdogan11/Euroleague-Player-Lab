"""Data-quality gate. Runs after fetch_season.py and before build.py; exits non-zero on any failure.

Checks: every club present with a plausible roster; no duplicate or future games; every played game has a
score; shot coordinates inside the court; per player per game, plotted attempts reconcile with box-score
attempts; every referenced photo and crest exists. Writes data/<season>/status.json for the site footer.

usage: python checks.py E2026
"""
import datetime as dt
import glob
import json
import os
import sys

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2026"
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", SEASON)
TODAY = dt.date.today().isoformat()
failures, warnings, stats = [], [], {}


def fail(msg):
    failures.append(msg)


def warn(msg):
    warnings.append(msg)


clubs_path = os.path.join(DATA, "clubs.json")
if not os.path.exists(clubs_path):
    fail("clubs.json missing"); clubs = []
else:
    clubs = json.load(open(clubs_path))["clubs"]
if len(clubs) != 20:
    fail(f"expected 20 clubs, found {len(clubs)}")

games_seen, total_players, total_games, total_shots, reconciled, photo_missing = {}, 0, 0, 0, 0, 0
for c in clubs:
    code = c["code"]
    path = os.path.join(DATA, f"{code}.json")
    if not os.path.exists(path):
        fail(f"{code}: club file missing"); continue
    d = json.load(open(path))
    if c.get("logo") and not os.path.exists(os.path.join(ROOT, c["logo"])):
        fail(f"{code}: crest file missing {c['logo']}")
    n = len(d["players"])
    total_players += n
    if n < 10 or n > 22:
        fail(f"{code}: implausible roster size {n}")
    for p in d["players"]:
        if p.get("photo") and not os.path.exists(os.path.join(ROOT, p["photo"])):
            fail(f"{code}: photo missing for {p['name']} ({p['photo']})")
        if not p.get("photo"):
            photo_missing += 1
    for g in d["games"]:
        total_games += 1
        if g["date"] > TODAY:
            fail(f"{code}: game {g['code']} dated in the future ({g['date']})")
        if (g["hs"] or 0) + (g["as"] or 0) <= 0:
            fail(f"{code}: game {g['code']} has no score")
        if code not in (g["home"], g["away"]):
            fail(f"{code}: game {g['code']} does not involve the club")
        key = g["code"]
        if key in games_seen and games_seen[key] != {g["home"], g["away"]}:
            fail(f"game {key} appears with different teams across club files")
        games_seen[key] = {g["home"], g["away"]}
    pids = {p["pid"] for p in d["players"]}
    for s in d["shots"]:
        total_shots += 1
        if not (-800 <= s["x"] <= 800 and -200 <= s["y"] <= 1450):
            fail(f"{code}: shot out of bounds x={s['x']} y={s['y']} game {s['game']}")
        if s["pts"] not in (2, 3):
            fail(f"{code}: shot with pts={s['pts']}")
    unknown = {s["pid"] for s in d["shots"]} - pids
    if unknown:
        warn(f"{code}: {len(unknown)} shooter ids not on the current roster (mid-season departures?)")
    # reconciliation: plotted attempts per player per game vs box-score attempts
    from collections import Counter
    plotted = Counter((s["pid"], s["game"]) for s in d["shots"])
    for b in d["box"]:
        want = (b["fga2"] or 0) + (b["fga3"] or 0)
        got = plotted.get((b["pid"], b["game"]), 0)
        if want != got:
            fail(f"{code}: {b['pid']} game {b['game']}: box {want} attempts, {got} plotted")
        else:
            reconciled += 1

games_unique = len(games_seen)
stats = {"season": SEASON, "checked_at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "clubs": len(clubs), "players": total_players,
         "games": games_unique, "shots": total_shots, "box_lines_reconciled": reconciled, "players_without_photo": photo_missing,
         "failures": len(failures), "warnings": len(warnings), "ok": not failures}
os.makedirs(DATA, exist_ok=True)
json.dump({**stats, "failure_list": failures[:50], "warning_list": warnings[:50]}, open(os.path.join(DATA, "status.json"), "w"), indent=1)

print(f"{SEASON}: {stats['clubs']} clubs, {stats['players']} players, {stats['games']} games, {stats['shots']} shots, {reconciled} box lines reconciled")
for w in warnings:
    print("WARN ", w)
for f in failures:
    print("FAIL ", f)
print("RESULT:", "OK" if not failures else f"{len(failures)} failure(s)")
sys.exit(0 if not failures else 1)
