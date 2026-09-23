"""The monitoring snapshot builds from the current warehouse and carries every field the status page reads.

usage: python tests/test_monitor.py
"""
import json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = dict(os.environ, XFG_API="http://127.0.0.1:9")          # unreachable on purpose: the API check must degrade, not fail
r = subprocess.run([sys.executable, os.path.join(ROOT, "model", "monitor.py"), "E2026"], capture_output=True, text=True, env=env)
m = json.load(open(os.path.join(ROOT, "teams", "E2026", "monitor.json")))
checks = {
    "collector exits 0 with the API unreachable": r.returncode == 0,
    "top-level sections present": all(k in m for k in ("pipeline", "freshness", "calibration", "api", "model")),
    "pipeline history is a list with the latest run": isinstance(m["pipeline"]["history"], list) and m["pipeline"]["history"][-1]["date"] == m["pipeline"]["last"]["date"],
    "freshness counts the schedule": m["freshness"].get("scheduled") == 380 and "rounds" in m["freshness"],
    "reference calibration covers the training season": len(m["calibration"]["reference_rounds"]) >= 30,
    "reference log loss beats the constant baseline": all(x["logloss"] < x["logloss_constant"] for x in m["calibration"]["reference_rounds"]),
    "api section reports unreachable": m["api"]["reachable"] is False,
    "production model identified": m["model"].get("stage") == "production" and len(m["model"].get("sha256", "")) == 12,
}
ok = True
for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k); ok &= bool(v)
print("ALL PASS" if ok else "FAILED")
sys.exit(0 if ok else 1)
