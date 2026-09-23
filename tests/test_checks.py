"""Proves the data-quality gate catches the failures it is meant to catch.

Builds a tiny synthetic season under data/TESTX/, runs checks.py against it, and asserts the verdict.
usage: python tests/test_checks.py
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEASON = "TESTX"
DATA = os.path.join(ROOT, "data", SEASON)


def club(code, shots, box, games):
    return {"club": code, "season": SEASON, "players": [{"pid": "P1", "code": "1", "name": "A, B", "dorsal": "1", "position": "Guard",
                                                         "height": 190, "birth": "2000-01-01", "country": "X", "photo": None}] * 12,
            "games": games, "upcoming": [], "shots": shots, "box": box}


def write(clubs):
    shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA)
    json.dump({"season": SEASON, "clubs": [{"code": c["club"], "name": c["club"], "short": c["club"], "logo": None} for c in clubs] + [{"code": f"Z{i}", "name": "z", "short": "z", "logo": None} for i in range(20 - len(clubs))]}, open(os.path.join(DATA, "clubs.json"), "w"))
    for c in clubs:
        json.dump(c, open(os.path.join(DATA, f"{c['club']}.json"), "w"))
    for i in range(20 - len(clubs)):
        json.dump(club(f"Z{i}", [], [], []), open(os.path.join(DATA, f"Z{i}.json"), "w"))


def run():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "checks.py"), SEASON], capture_output=True, text=True)
    return r.returncode, r.stdout


game = {"code": 1, "round": 1, "date": "2026-01-01", "home": "AAA", "away": "Z0", "hs": 80, "as": 70, "phase": "RS"}
shot = lambda x, y, made=True: {"game": 1, "pid": "P1", "x": x, "y": y, "made": made, "pts": 2, "zone": "A", "q": 1, "clock": "09:00", "fastbreak": False, "second_chance": False}
box = lambda fga2: {"game": 1, "pid": "P1", "min": "20:00", "pts": 4, "fgm2": 2, "fga2": fga2, "fgm3": 0, "fga3": 0, "ftm": 0, "fta": 0, "oreb": 0, "dreb": 0, "reb": 0,
                    "ast": 0, "stl": 0, "tov": 0, "blk": 0, "blka": 0, "pf": 0, "fd": 0, "pir": 4, "plusminus": 0}

cases = [
    ("clean season passes", [club("AAA", [shot(10, 20), shot(-30, 40)], [box(2)], [game])], 0, None),
    ("attempt mismatch fails", [club("AAA", [shot(10, 20)], [box(2)], [game])], 1, "box 2 attempts, 1 plotted"),
    ("out-of-bounds shot fails", [club("AAA", [shot(10, 20), shot(-30, 9999)], [box(2)], [game])], 1, "out of bounds"),
    ("future game fails", [club("AAA", [shot(10, 20), shot(-30, 40)], [box(2)], [dict(game, date="2099-01-01")])], 1, "future"),
    ("tiny roster fails", [dict(club("AAA", [], [], []), players=[])], 1, "roster size"),
]
ok = True
for name, clubs, want_code, want_text in cases:
    write(clubs)
    code, out = run()
    passed = code == want_code and (want_text is None or want_text in out)
    ok &= passed
    print(("PASS" if passed else "FAIL"), name, f"(exit {code})")
    if not passed:
        print(out)
shutil.rmtree(DATA, ignore_errors=True)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
