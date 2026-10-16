"""Proves the RAPM fit (rapm.py) recovers a player's effect from stints where he shares the floor with everyone else.

Builds a synthetic season of random fives from two 10-man clubs, gives one player +12 points per 100 possessions on
offence and another -12 on defence, and asserts the fit ranks them first and last with the right signs.
usage: python tests/test_rapm.py
"""
import os
import random
import sys
import tempfile
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import rapm

rng = random.Random(7)
HOME, AWAY = [f"H{i}" for i in range(10)], [f"A{i}" for i in range(10)]
rows = []
for game in range(1, 41):
    for stint in range(30):
        five = {"H": sorted(rng.sample(HOME, 5)), "A": sorted(rng.sample(AWAY, 5))}
        for c, o in (("H", "A"), ("A", "H")):
            poss = 6
            rate = 1.05 + (0.12 if "H0" in five[c] else 0) + (0.12 if "A9" in five[o] else 0)
            pts = sum(2 for _ in range(poss) if rng.random() < rate / 2)
            rows.append((game, c, stint, five[c], 60, pts, poss))
con = duckdb.connect()
path = os.path.join(tempfile.mkdtemp(), "stints.parquet")
con.execute("create table s (game int, club varchar, stint int, players varchar[], sec int, pts int, fga int)")
con.executemany("insert into s values (?, ?, ?, ?, ?, ?, ?)", rows)
con.execute(f"copy (select *, 0 oreb, 0 tov, 0 fta from s) to '{path}' (format parquet)")

res = rapm.fit(con, path)
ps = res["players"]
best = max(ps, key=lambda p: ps[p]["o"])
worst = min(ps, key=lambda p: ps[p]["d"])
assert best == "H0" and ps["H0"]["o"] > 3, (best, ps["H0"])
assert worst == "A9" and ps["A9"]["d"] < -3, (worst, ps["A9"])
assert all(abs(v["t"] - v["o"] - v["d"]) <= 0.11 for v in ps.values())
assert res["lambda"] in rapm.LAMBDAS and res["games"] == 40
print(f"rapm: penalty {res['lambda']}, H0 offence {ps['H0']['o']:+.1f}, A9 defence {ps['A9']['d']:+.1f}: PASS")
