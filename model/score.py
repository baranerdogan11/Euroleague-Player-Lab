"""Score every shot of a season with the xFG model and write warehouse/<season>/shots_xfg.parquet.

Shooter effects start from last season's shrunk effects (decayed, since rosters and roles change) and update
sequentially through the current season, so a player's xFG reflects his own record as it accumulates.

usage: python model/score.py E2026
"""
import os
import sys
import duckdb
import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xfg import featurize, load_shots  # noqa: E402

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2026"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "model")
W = os.path.join(ROOT, "warehouse", SEASON)
PRIOR_DECAY = 0.6

bundle = joblib.load(os.path.join(MODEL_DIR, "xfg_model.joblib"))
model, feats, k = bundle["model"], bundle["features"], bundle["k_shrink"]
out_path = os.path.join(W, "shots_xfg.parquet")
raw = load_shots(SEASON)
if raw.empty:
    pd.DataFrame({"game": pd.Series(dtype="int32"), "seq": pd.Series(dtype="int32"), "player": pd.Series(dtype=str), "xfg": pd.Series(dtype=float), "xfg_ctx": pd.Series(dtype=float)}).to_parquet(out_path, index=False)
    print(f"{SEASON}: no shots yet; wrote empty shots_xfg.parquet")
    sys.exit(0)
df = featurize(raw)
df["zone"] = pd.Categorical(df.zone.astype(str), categories=bundle["categories"]["zone"])

if "shooter" in feats:
    prior_path = os.path.join(MODEL_DIR, f"shooter_effects_{bundle['trained_on']}.parquet")
    prior = pd.read_parquet(prior_path).set_index("player") if os.path.exists(prior_path) else pd.DataFrame(columns=["n", "effect"])
    acc, n, shooter = {}, {}, np.zeros(len(df))
    for p in df.player.unique():
        if p in prior.index:
            acc[p] = float(prior.loc[p, "effect"]) * (float(prior.loc[p, "n"]) + k) * PRIOR_DECAY
            n[p] = float(prior.loc[p, "n"]) * PRIOR_DECAY
    for i, p in enumerate(df.player.values):
        shooter[i] = acc.get(p, 0.0) / (n.get(p, 0.0) + k)
    df["shooter"] = shooter
    xfg = model.predict_proba(df[feats])[:, 1]
    # one sequential refinement pass: update running residuals with this season's shots (earlier shots only)
    resid = df.made.values - xfg
    shooter2 = np.zeros(len(df))
    acc2, n2 = dict(acc), dict(n)
    for i, (p, r) in enumerate(zip(df.player.values, resid)):
        shooter2[i] = acc2.get(p, 0.0) / (n2.get(p, 0.0) + k)
        acc2[p] = acc2.get(p, 0.0) + r; n2[p] = n2.get(p, 0.0) + 1
    df["shooter"] = shooter2
    xfg = model.predict_proba(df[feats])[:, 1]
else:
    xfg = model.predict_proba(df[feats])[:, 1]

# context-only expectation: the same shot taken by a league-average shooter (shooter term at its prior of zero)
xfg_ctx = model.predict_proba(df.assign(shooter=0.0)[feats])[:, 1] if "shooter" in feats else xfg
out = pd.DataFrame({"game": df.game.values, "seq": df.seq.values, "player": df.player.values, "xfg": np.round(xfg, 4), "xfg_ctx": np.round(xfg_ctx, 4)})
out.to_parquet(out_path, index=False)
made = df.made.mean()
print(f"{SEASON}: scored {len(out)} shots; mean xFG {xfg.mean():.3f} vs actual {made:.3f}")
