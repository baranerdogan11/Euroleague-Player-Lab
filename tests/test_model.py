"""Smoke test for the deployed xFG model: it loads, scores real fixture shots, and behaves like a probability.

usage: python tests/test_model.py
"""
import json
import os
import sys
import joblib
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
from xfg import featurize  # noqa: E402

bundle = joblib.load(os.path.join(ROOT, "model", "xfg_model.joblib"))
card = json.load(open(os.path.join(ROOT, "model", "model_card.json")))
rows = json.load(open(os.path.join(ROOT, "tests", "fixtures", "points_1.json")))["Rows"]
shots = [r for r in rows if r["ID_ACTION"].strip() in ("2FGM", "2FGA", "3FGM", "3FGA")]
df = pd.DataFrame({"game": 1, "seq": [r["NUM_ANOT"] for r in shots], "player": [r["ID_PLAYER"].strip()[1:] for r in shots], "club": [r["TEAM"].strip() for r in shots],
                   "x": [r["COORD_X"] for r in shots], "y": [r["COORD_Y"] for r in shots], "made": [r["ID_ACTION"].strip().endswith("M") for r in shots],
                   "pts": [3 if r["ID_ACTION"].strip().startswith("3") else 2 for r in shots], "zone": [r["ZONE"].strip() for r in shots],
                   "minute": [r["MINUTE"] for r in shots], "clock": [r["CONSOLE"] for r in shots], "fastbreak": False, "second_chance": False, "points_off_tov": False,
                   "score_home": [r["POINTS_A"] for r in shots], "score_away": [r["POINTS_B"] for r in shots], "date": "2025-09-30", "home": "IST", "away": "TEL", "round": 1})
f = featurize(df)
f["zone"] = pd.Categorical(f.zone.astype(str), categories=bundle["categories"]["zone"])
if "shooter" in bundle["features"]:
    f["shooter"] = 0.0
p = bundle["model"].predict_proba(f[bundle["features"]])[:, 1]
checks = {
    "model loads with a feature list": len(bundle["features"]) > 5,
    "scores every fixture shot": len(p) == len(df) and len(p) > 100,
    "probabilities in (0,1)": bool(np.all((p > 0.02) & (p < 0.98))),
    "mean xFG in a plausible band": 0.35 < p.mean() < 0.60,
    "layups rated above threes": p[(f.dist < 1.5).values].mean() > p[(f.three == 1).values].mean(),
    "card metrics beat the zone baseline": card["metrics_test"][card["chosen"]]["logloss"] < card["metrics_test"]["zone_fg"]["logloss"],
    "no leaking flags among features": not any(x in bundle["features"] for x in ("fastbreak", "second_chance", "points_off_tov")),
}
ok = True
for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k); ok &= bool(v)
print(f"fixture: {len(p)} shots, mean xFG {p.mean():.3f}, actual FG {df.made.mean():.3f}")
print("ALL PASS" if ok else "FAILED")
sys.exit(0 if ok else 1)
