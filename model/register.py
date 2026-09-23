"""Model registry: append the current model to model/registry.json with its hash, metrics and data lineage.

usage: python model/register.py [--activate]
"""
import datetime
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(ROOT, "model")
REG = os.path.join(M, "registry.json")

sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
card = json.load(open(os.path.join(M, "model_card.json")))
manifest_path = os.path.join(ROOT, "warehouse", card["trained_on"], "manifest.json")
data_hash = sha(os.path.join(ROOT, "warehouse", card["trained_on"], "shots.parquet")) if os.path.exists(manifest_path) else None
entry = {"name": "xfg", "version": card["version"], "sha256": sha(os.path.join(M, "xfg_model.joblib")), "registered_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
         "trained_on": card["trained_on"], "training_shots_sha256": data_hash, "n_shots": card["n_shots"], "features": card["features"], "chosen": card["chosen"],
         "metrics_test": card["metrics_test"][card["chosen"]], "baseline_zone_logloss": card["metrics_test"]["zone_fg"]["logloss"], "algorithm": card["algorithm"],
         "stage": "production" if "--activate" in sys.argv else "candidate"}
reg = json.load(open(REG)) if os.path.exists(REG) else {"models": []}
reg["models"] = [m for m in reg["models"] if m["sha256"] != entry["sha256"]]
if entry["stage"] == "production":
    for m in reg["models"]:
        if m.get("stage") == "production":
            m["stage"] = "archived"
reg["models"].append(entry)
json.dump(reg, open(REG, "w"), indent=1)
print(f"registered xfg {entry['version']} ({entry['sha256'][:12]}) as {entry['stage']}; {len(reg['models'])} entries")
