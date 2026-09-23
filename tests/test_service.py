"""Contract tests for the xFG service, run against the app in-process.

usage: python tests/test_service.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "service"))
from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402

c = TestClient(app)
results = {}
h = c.get("/health"); results["health 200 with model version"] = h.status_code == 200 and "model_version" in h.json()
m = c.get("/model"); results["model card exposes metrics"] = m.status_code == 200 and "metrics_test" in m.json()["card"]
layup = {"x": 20, "y": 60, "pts": 2, "minute": 5, "clock": "07:30", "home": True, "margin": 0}
three = {"x": 0, "y": 720, "pts": 3, "minute": 5, "clock": "07:30", "home": True, "margin": 0}
corner = {"x": 690, "y": 40, "pts": 3, "minute": 38, "clock": "00:20", "home": False, "margin": -3}
p = c.post("/predict", json={"shots": [layup, three, corner]})
ok = p.status_code == 200
body = p.json() if ok else {}
results["predict 200"] = ok
results["one prediction per shot, in (0,1)"] = ok and len(body["predictions"]) == 3 and all(0 < q["xfg"] < 1 for q in body["predictions"])
results["layup rated above the three"] = ok and body["predictions"][0]["xfg"] > body["predictions"][1]["xfg"]
results["expected points consistent"] = ok and abs(body["predictions"][1]["expected_points"] - 3 * body["predictions"][1]["xfg"]) < 0.01
results["response carries model version header"] = ok and p.headers.get("x-model-version") == body["model_version"]
results["unknown player falls back to context"] = ok and c.post("/predict", json={"shots": [dict(three, player="000000")]}).json()["predictions"][0]["shooter_known"] is False
known = c.post("/predict", json={"shots": [dict(three, player="002100")]}).json()["predictions"][0]
results["known shooter is flagged"] = known["shooter_known"] is True
# the shooter term is weak per player (trees bin it coarsely) but must point the right way on average
import pandas as pd, numpy as np
eff = pd.read_parquet(os.path.join(ROOT, "model", "shooter_effects_E2025.parquet")).set_index("player"); eff = eff[eff.n >= 100].sort_values("effect")
probe = [dict(three), dict(layup), {"x": 660, "y": 60, "pts": 3, "minute": 15, "clock": "05:00", "home": True, "margin": 0}]
shift = lambda pl: np.mean([q["xfg"] - q["xfg_context"] for q in c.post("/predict", json={"shots": [dict(s, player=pl) for s in probe]}).json()["predictions"]])
results["shooter effect right way on average (best vs worst 10)"] = np.mean([shift(p) for p in eff.index[-10:]]) > np.mean([shift(p) for p in eff.index[:10]])
bad = c.post("/predict", json={"shots": [dict(layup, pts=1)]}); results["rejects pts other than 2 or 3 (422)"] = bad.status_code == 422
bad2 = c.post("/predict", json={"shots": [dict(layup, x=5000)]}); results["rejects off-court coordinates (422)"] = bad2.status_code == 422
big = c.post("/predict", json={"shots": [layup] * 501}); results["rejects batches over 500 (422)"] = big.status_code == 422
empty = c.post("/predict", json={"shots": []}); results["rejects empty batch (422)"] = empty.status_code == 422
all_ok = True
for k, v in results.items():
    print(("PASS " if v else "FAIL ") + k); all_ok &= bool(v)
if ok:
    print("sample:", {k: body["predictions"][i]["xfg"] for i, k in enumerate(["layup", "top-of-key 3", "corner 3 late, away, down 3"])})
print("ALL PASS" if all_ok else "FAILED")
sys.exit(0 if all_ok else 1)
