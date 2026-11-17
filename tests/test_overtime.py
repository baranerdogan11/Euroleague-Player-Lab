"""Overtimes: the play-by-play feed files every overtime under ExtraTime, so events.py tells them apart by the game minute
(41-45 the first overtime, 46-50 the second; an end-of-period marker carries the next minute). Without that, a
double-overtime game puts both overtimes in period 5, the lineup layer counts five minutes of overtime instead of ten and
leaves the game out (all four multi-overtime games of 2025-26 were left out this way).

One synthetic game in the feed's format, AAA v BBB, the ten starters on the floor for all 50 minutes of a
double-overtime game. events.py then lineups.py must give the overtimes periods 5 and 6 and keep the game
in the lineup layer with 50 minutes for every starter.

usage: python tests/test_overtime.py
"""
import json
import os
import shutil
import subprocess
import sys
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEASON = "TESTOT"
CACHE, W = os.path.join(ROOT, "cache", SEASON), os.path.join(ROOT, "warehouse", SEASON)
for d in (CACHE, W):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)

seq = 0
def ev(playtype, minute, clock=None, club=None, player=None):
    global seq
    seq += 1
    return {"NUMBEROFPLAY": seq, "CODETEAM": club or "", "PLAYER_ID": player and f"P{player}", "PLAYTYPE": playtype, "MINUTE": minute,
            "MARKERTIME": clock or "", "POINTS_A": 0, "POINTS_B": 0, "PLAYINFO": ""}

pbp = {}
for key, start in (("FirstQuarter", 1), ("SecondQuarter", 11), ("ThirdQuarter", 21), ("ForthQuarter", 31)):
    pbp[key] = [ev("BP", start), ev("2FGA", start + 4, "05:00", "AAA", "A1"), ev("EP", start + 10)]
pbp["ExtraTime"] = [ev("BP", 41), ev("2FGA", 43, "02:30", "BBB", "B1"), ev("EP", 46),       # first overtime
                    ev("BP", 46), ev("2FGA", 48, "02:30", "AAA", "A2"), ev("EP", 51), ev("EG", 51)]   # second overtime
json.dump(pbp, open(os.path.join(CACHE, "pbp_1.json"), "w"))

box = [{"game": 1, "club": c, "player": f"{c[0]}{i}", "starter": True, "minutes": 50.0} for c in ("AAA", "BBB") for i in range(1, 6)]
con = duckdb.connect()
for name, rs in (("box", box), ("games", [{"game": 1, "home": "AAA", "away": "BBB", "played": True}])):
    tmp = os.path.join(W, name + ".json")
    json.dump(rs, open(tmp, "w"))
    con.execute(f"copy (select * from read_json_auto('{tmp}')) to '{os.path.join(W, name + '.parquet')}' (format parquet)")
    os.remove(tmp)

ok = True
for script in ("events.py", "lineups.py"):
    r = subprocess.run([sys.executable, os.path.join(ROOT, script), SEASON], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    ok = ok and r.returncode == 0
if ok:
    periods = dict(con.execute(f"select seq, period from read_parquet('{W}/events.parquet') where seq > 12").fetchall())
    on = con.execute(f"select count(*), min(sec), max(sec) from read_parquet('{W}/oncourt.parquet')").fetchone()
    checks = [
        ("first overtime is period 5, its end marker included", [periods[s] for s in (13, 14, 15)] == [5, 5, 5]),
        ("second overtime is period 6, from its opening marker to the final buzzer", [periods[s] for s in (16, 17, 18, 19)] == [6, 6, 6, 6]),
        ("the game stays in the lineup layer", json.load(open(os.path.join(W, "lineups_skipped.json"))) == []),
        ("every starter is on the floor for all 50 minutes", on == (10, 3000, 3000)),
    ]
    for name, passed in checks:
        print(("PASS " if passed else "FAIL ") + name)
        ok = ok and passed
for d in (CACHE, W):
    shutil.rmtree(d, ignore_errors=True)
print("ALL PASS" if ok else "FAILED")
sys.exit(0 if ok else 1)
