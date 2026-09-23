"""Builds a one-game warehouse from a real fixture (Efes vs Maccabi, 2025-26 round 1) and runs every
warehouse assertion against it, so the parser and the reconciliation checks are exercised on real feed data.

usage: python tests/test_warehouse.py
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
SEASON = "TESTW"
CACHE = os.path.join(ROOT, "cache", SEASON)
W = os.path.join(ROOT, "warehouse", SEASON)


def person(code, name):
    return {"type": "J", "active": True, "startDate": "2025-09-01T00:00:00", "endDate": "2026-06-30T00:00:00", "dorsal": "1", "positionName": "Guard",
            "person": {"code": code, "name": name, "birthDate": "1995-01-01T00:00:00", "country": {"name": "X"}, "height": 190}}


shutil.rmtree(CACHE, ignore_errors=True); shutil.rmtree(W, ignore_errors=True)
os.makedirs(CACHE)
box = json.load(open(os.path.join(FIX, "box_1.json")))
clubs = ["IST"] + [f"Z{i:02d}" for i in range(18)] + ["TEL"]   # circle method pairs clubs[0] with clubs[19] in round 1: the fixture game
json.dump([{"code": c, "name": c, "abbreviatedName": c, "country": {"name": "X"}, "city": "Y"} for c in clubs], open(os.path.join(CACHE, "clubs.json"), "w"))
for c in clubs:
    people = [person(p["Player_ID"].strip()[1:], p["Player"].strip()) for side in box["Stats"] for p in side["PlayersStats"] if p["Team"].strip() == c] or [person(f"9{c[1:]}{i:03d}", f"Z, {i}") for i in range(12)]
    json.dump(people, open(os.path.join(CACHE, f"roster_{c}.json"), "w"))
# schedule: the fixture game plus a plausible 38-round round-robin so the per-club game-count assertion holds
games = [{"code": 1, "date": "2025-09-30T17:00:00.000Z", "status": "final", "round": {"round": 1}, "phaseType": {"code": "RS"},
          "home": {"code": "IST", "score": 90}, "away": {"code": "TEL", "score": 84}}]
code = 2
for rnd in range(1, 39):
    order = clubs[1:]; k = (rnd - 1) % 19
    rotated = [clubs[0]] + order[k:] + order[:k]
    for i in range(10):
        h, a = rotated[i], rotated[19 - i]
        if rnd == 1 and {h, a} == {"IST", "TEL"}:
            continue
        games.append({"code": code, "date": f"2027-01-{(rnd % 28) + 1:02d}T18:00:00.000Z", "status": "confirmed", "round": {"round": rnd}, "phaseType": {"code": "RS"},
                      "home": {"code": h, "score": 0}, "away": {"code": a, "score": 0}}); code += 1
json.dump(games, open(os.path.join(CACHE, "games_latest.json"), "w"))
shutil.copy(os.path.join(FIX, "points_1.json"), os.path.join(CACHE, "points_1.json"))
shutil.copy(os.path.join(FIX, "box_1.json"), os.path.join(CACHE, "box_1.json"))

r1 = subprocess.run([sys.executable, os.path.join(ROOT, "warehouse.py"), SEASON], capture_output=True, text=True)
print(r1.stdout.strip())
r2 = subprocess.run([sys.executable, os.path.join(ROOT, "warehouse_tests.py"), SEASON], capture_output=True, text=True)
print(r2.stdout.strip())
ok = r1.returncode == 0 and r2.returncode == 0
if r1.returncode == 0:
    import duckdb
    n_shots, n_box = duckdb.query(f"select (select count(*) from read_parquet('{W}/shots.parquet')), (select count(*) from read_parquet('{W}/box.parquet'))").fetchone()
    print(f"fixture parsed: {n_box} box lines, {n_shots} shots")
    ok = ok and n_box == 24 and n_shots > 100
shutil.rmtree(CACHE, ignore_errors=True); shutil.rmtree(W, ignore_errors=True)
print("ALL PASS" if ok else "FAILED")
sys.exit(0 if ok else 1)
