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
    return {"club": code, "season": SEASON, "players": [{"pid": f"P{i}", "code": str(i), "name": "A, B", "dorsal": str(i), "position": "Guard",
                                                         "height": 190, "birth": "2000-01-01", "country": "X", "photo": None} for i in range(1, 13)],
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
    ("duplicate players fail", [dict(club("AAA", [shot(10, 20), shot(-30, 40)], [box(2)], [game]), players=club("AAA", [], [], [])["players"] * 2)], 1, "duplicate players"),
    ("a re-signed player listed twice passes", [dict(club("AAA", [shot(10, 20), shot(-30, 40)], [box(2)], [game]), players=club("AAA", [], [], [])["players"] + [dict(club("AAA", [], [], [])["players"][0])])], 0, None),
    ("large roster passes", [dict(club("AAA", [shot(10, 20), shot(-30, 40)], [box(2)], [game]), players=[dict(p, pid=f"P{i}", code=str(i)) for i, p in enumerate(club("AAA", [], [], [])["players"] * 2, 1)])], 0, "large roster"),
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

# ---- the build-to-build drift check (drift.py): what a replayed or corrupt feed looks like against the previous build
sys.path.insert(0, ROOT)
import drift   # noqa: E402

def L(games, rows, built="t"):
    return {"built": built, "games": games, "rows": rows}

def R(pid="P1", c="AAA", gp=5, pts=60, reb=20, ast=10, mins=120.0, fga2=30, fga3=20, fta=15):
    return {"pid": pid, "c": c, "name": f"PLAYER, {pid}", "gp": gp, "pts": pts, "reb": reb, "ast": ast, "min": mins, "fga2": fga2, "fga3": fga3, "fta": fta}

ten = [R(pid=f"P{i}") for i in range(1, 11)]
base = L({"AAA": 5}, ten)
drift_cases = [
    ("drift: unchanged build passes", base, L({"AAA": 5}, ten), 0, 0),
    ("drift: first build has nothing to compare", None, L({"AAA": 5}, ten), 0, 0),
    ("drift: one new game within a game's worth passes", base, L({"AAA": 6}, [R(pid=f"P{i}", gp=6, pts=95, reb=30, mins=150.0) for i in range(1, 11)]), 0, 0),
    ("drift: points beyond a game's worth fail", base, L({"AAA": 6}, [R(pid="P1", gp=6, pts=130)] + ten[1:]), 1, 0),
    ("drift: games played going backwards fail", base, L({"AAA": 5}, [R(pid="P1", gp=4, pts=50)] + ten[1:]), 1, 0),
    ("drift: a club's games going backwards fail", base, L({"AAA": 4}, ten), 1, 0),
    ("drift: a box-score correction warns", base, L({"AAA": 5}, [R(pid="P1", pts=62)] + ten[1:]), 0, 1),
    ("drift: a total going down with a new game warns", base, L({"AAA": 6}, [R(pid="P1", gp=6, reb=18)] + ten[1:]), 0, 1),
    ("drift: one line gone warns", base, L({"AAA": 5}, ten[1:]), 0, 1),
    ("drift: half the lines gone fail", base, L({"AAA": 5}, ten[5:]), 1, 0),
    ("drift: points above xFG falling with a new game passes", L({"AAA": 5}, [{**R(), "pax": 6.5}]), L({"AAA": 6}, [{**R(gp=6, pts=70), "pax": -3.1}]), 0, 0),
    ("drift: points above xFG beyond a game's worth fail", L({"AAA": 5}, [{**R(), "pax": 6.5}]), L({"AAA": 6}, [{**R(gp=6, pts=70), "pax": 40.0}]), 1, 0),
    ("drift: a stat the previous build lacked is not checked", base, L({"AAA": 5}, [{**r, "pax": 30.0, "rapm": 2.0} for r in ten]), 0, 0),
    ("drift: RAPM moving with no new game warns", L({"AAA": 5}, [{**R(), "rapm": 1.2}]), L({"AAA": 5}, [{**R(), "rapm": 1.9}]), 0, 1),
    ("drift: RAPM moving with a new game passes", L({"AAA": 5, "BBB": 5}, [{**R(), "rapm": 1.2}]), L({"AAA": 5, "BBB": 6}, [{**R(), "rapm": 1.9}]), 0, 0),
    ("drift: a transfer is a new line, not a jump", base, L({"AAA": 5, "BBB": 5}, ten + [R(pid="P1", c="BBB", gp=1, pts=20)]), 0, 0),
]
for name, old, new, want_f, want_w in drift_cases:
    fails, warns = drift.check(old, new)
    passed = len(fails) == want_f and len(warns) == want_w
    ok &= passed
    print(("PASS" if passed else "FAIL"), name, f"({len(fails)} failure(s), {len(warns)} warning(s))")
    if not passed:
        print(fails, warns)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
