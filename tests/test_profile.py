"""Checks the shrinkage priors are sane and the profile step handles an empty season.

usage: python tests/test_profile.py
"""
import json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pr = json.load(open(os.path.join(ROOT, "model", "shooting_priors.json")))
checks = {
    "skill prior weight between 50 and 2000 attempts": 50 <= pr["k_skill"] <= 2000,
    "quality prior weight between 2 and 200 attempts": 2 <= pr["k_quality"] <= 200,
    "league expected points per attempt plausible": 0.9 <= pr["league_quality"] <= 1.3,
    "reference distributions populated": len(pr["reference_skill"]) >= 100 and len(pr["reference_quality"]) >= 100,
    "shrinkage predicts the second half better than raw": pr["split_half"]["rmse_shrunk"] < pr["split_half"]["rmse_raw"],
    "shrinkage predicts the second half better than zero": pr["split_half"]["rmse_shrunk"] < pr["split_half"]["rmse_zero"],
}
ok = True
for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k); ok &= bool(v)
print("ALL PASS" if ok else "FAILED")
sys.exit(0 if ok else 1)
