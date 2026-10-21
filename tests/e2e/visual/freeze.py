"""Freezes the data the screenshot tests (tests/e2e/visual.spec.js) draw from, so the nightly data commits do not change
the pictures: the META line of index.html and the few teams/<season> files the cover, a club page and a player page fetch.
Run it only when the pictures should show newer data, then refresh the baselines (see visual.spec.js).
usage: python tests/e2e/visual/freeze.py
"""
import json
import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CLUB = "ULK"

html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
meta = json.loads(re.search(r"^const META = (.*);$", html, re.M).group(1))
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(os.path.join(OUT, "lineups"))
json.dump(meta, open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
src = os.path.join(ROOT, "teams", meta["season"])
for f in ("roster.json", "status.json", f"{CLUB}.json", f"lineups/{CLUB}.json"):
    shutil.copy(os.path.join(src, f), os.path.join(OUT, f))
print(f"froze {meta['season']} as built {meta.get('built')} into {OUT}")
