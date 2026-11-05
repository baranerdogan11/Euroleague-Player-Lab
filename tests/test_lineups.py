"""Lineup layer: a game whose substitution log disagrees with the box score by more than three minutes is left out of
the stints and oncourt tables (and listed in lineups_skipped.json) instead of failing the whole update, while a clean
game next to it is kept.

Three synthetic games with the same play-by-play (A6 subs in for A1 at 05:00 of Q1, A1 comes back to start Q2): in
game 1 the box score agrees (A1 35 min, A6 5 min); in game 2 it says A1 30 and A6 10, as when the feed garbles a clock.
Game 3 agrees with the box score but is entered the way the feed sent it on 2026-11-05: the Q2-opening substitutions
come before Q1's end marker, right after a play at 00:48 of Q1, with a garbled clock ("24.?"). They belong at the start
of Q2, not at 00:48 of Q2, so game 3 must be kept with the right minutes.

usage: python tests/test_lineups.py
"""
import json
import os
import shutil
import subprocess
import sys
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEASON = "TESTL"
W = os.path.join(ROOT, "warehouse", SEASON)
shutil.rmtree(W, ignore_errors=True)
os.makedirs(W)

events, box, games = [], [], []
for g in (1, 2, 3):
    games.append({"game": g, "home": "AAA", "away": "BBB", "played": True})
    seq = 0
    def ev(period, playtype, club=None, player=None, clock_sec=None, minute=None):
        global seq
        seq += 1
        events.append({"game": g, "seq": seq, "period": period, "club": club, "player": player, "playtype": playtype, "clock_sec": clock_sec, "minute": minute})
    for per in (1, 2, 3, 4):
        ev(per, "BP")
        if per == 1:
            ev(1, "2FGM", "AAA", "A2", 540)
            ev(1, "OUT", "AAA", "A1", 300)
            ev(1, "IN", "AAA", "A6", 300)
            ev(1, "2FGM", "BBB", "B2", 200)
            if g == 3:
                ev(1, "2FGM", "BBB", "B3", 48, 10)
                ev(2, "OUT", "AAA", "A6", None, 11)
                ev(2, "IN", "AAA", "A1", None, 11)
        if per == 2 and g == 3:
            ev(2, "2FGM", "BBB", "B2", 300, 15)
        if per == 2 and g != 3:
            ev(2, "OUT", "AAA", "A6", 600)
            ev(2, "IN", "AAA", "A1", 600)
        ev(per, "EP")
    ev(4, "EG")
    a1, a6 = (30.0, 10.0) if g == 2 else (35.0, 5.0)
    for p, m in [("A1", a1), ("A2", 40.0), ("A3", 40.0), ("A4", 40.0), ("A5", 40.0), ("A6", a6)]:
        box.append({"game": g, "club": "AAA", "player": p, "starter": p != "A6", "minutes": m})
    for p in ("B1", "B2", "B3", "B4", "B5"):
        box.append({"game": g, "club": "BBB", "player": p, "starter": True, "minutes": 40.0})

con = duckdb.connect()
for name, rs in (("events", events), ("box", box), ("games", games)):
    tmp = os.path.join(W, name + ".json")
    json.dump(rs, open(tmp, "w"))
    con.execute(f"copy (select * from read_json_auto('{tmp}')) to '{os.path.join(W, name + '.parquet')}' (format parquet)")
    os.remove(tmp)

r = subprocess.run([sys.executable, os.path.join(ROOT, "lineups.py"), SEASON], capture_output=True, text=True)
print(r.stdout.strip() or r.stderr.strip())
ok = r.returncode == 0
if ok:
    st_games = {g for (g,) in con.execute(f"select distinct game from read_parquet('{W}/stints.parquet')").fetchall()}
    on_games = {g for (g,) in con.execute(f"select distinct game from read_parquet('{W}/oncourt.parquet')").fetchall()}
    skipped = json.load(open(os.path.join(W, "lineups_skipped.json")))
    checks = [
        ("clean games kept in stints and oncourt", st_games == {1, 3} and on_games == {1, 3}),
        ("broken game listed in lineups_skipped.json with its two players", [s["game"] for s in skipped] == [2] and {p["player"] for p in skipped[0]["players"]} == {"A1", "A6"}),
        ("clean games' minutes match the box score (garbled period-opening subs placed at the period start)", con.execute(f"select max(abs(sec / 60.0 - box_min)) from read_parquet('{W}/oncourt.parquet')").fetchone()[0] < 0.01),
    ]
    for name, passed in checks:
        print(("PASS " if passed else "FAIL ") + name)
        ok = ok and passed
shutil.rmtree(W, ignore_errors=True)
print("ALL PASS" if ok else "FAILED")
sys.exit(0 if ok else 1)
