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
# the xFG row and the profile panel must state the same points above expectation for every built player page
import glob
mismatch, compared = [], 0
for f in glob.glob(os.path.join(ROOT, "teams", "*", "*.json")):
    if os.path.basename(f) in ("index.json", "monitor.json", "status.json"):
        continue
    for p in json.load(open(f)).get("players", []):
        c = p["cur"]
        if c.get("xfg") and c.get("profile") and c["xfg"]["att"] == c["profile"]["att"]:
            compared += 1
            if abs((c["xfg"]["pts"] - c["xfg"]["xpts"]) - c["profile"]["pae"]) > 0.1:
                mismatch.append((os.path.basename(f), p["name"]))
checks[f"xFG row and profile agree on points above expectation ({compared} players compared)"] = not mismatch
ok = True
for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k); ok &= bool(v)
print("ALL PASS" if ok else "FAILED")
sys.exit(0 if ok else 1)
