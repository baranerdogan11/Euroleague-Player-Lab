"""Expected field-goal model (xFG): the probability a shot goes in given where and when it was taken.

Trained on a past season's warehouse. Context features only in the base model (location, distance, angle,
shot value, clock, game state, transition flags); shooter quality enters as a separate, leak-free feature:
each shooter's shrunk residual (made minus xFG) accumulated over his earlier shots only. Validation is by
time: the last 25% of games by date are held out. Outputs the fitted model, a model card with metrics and
calibration, and per-shooter effects for use as priors next season.

usage: python model/xfg.py E2025
"""
import datetime
import json
import os
import sys
import duckdb
import joblib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2025"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = os.path.join(ROOT, "warehouse", SEASON)
OUT = os.path.join(ROOT, "model")
K_SHRINK = 150.0       # attempts at which a shooter's own record gets half the weight of the league prior
SEED = 7

from features import NUMERIC, BINARY, CATEG, FEATURES, featurize  # noqa: E402


def load_shots(season):
    con = duckdb.connect()
    w = os.path.join(ROOT, "warehouse", season)
    q = f"""
    select s.game, s.seq, s.player, s.club, s.x, s.y, s.made, s.pts, s.zone, s.minute, s.clock, s.fastbreak, s.second_chance, s.points_off_tov,
           s.score_home, s.score_away, g.date, g.home, g.away, g.round
    from read_parquet('{w}/shots.parquet') s join read_parquet('{w}/games.parquet') g using (game)
    order by g.date, s.game, s.minute, s.seq"""
    return con.execute(q).df()


def make_model(seed=SEED):
    return HistGradientBoostingClassifier(learning_rate=0.05, max_iter=600, max_leaf_nodes=31, min_samples_leaf=40, l2_regularization=1.0,
                                          early_stopping=True, validation_fraction=0.1, n_iter_no_change=40, categorical_features=[FEATURES.index("zone")],
                                          random_state=seed)


def shooter_effects(df, resid, k=K_SHRINK):
    """Sequential shrunk residual per shooter: uses only shots before each shot (leak-free feature)."""
    prior = np.zeros(len(df))
    acc, n = {}, {}
    for i, (p, r) in enumerate(zip(df.player.values, resid)):
        prior[i] = acc.get(p, 0.0) / (n.get(p, 0) + k)
        acc[p] = acc.get(p, 0.0) + r; n[p] = n.get(p, 0) + 1
    final = pd.DataFrame({"player": list(acc), "n": [n[p] for p in acc], "effect": [acc[p] / (n[p] + k) for p in acc]})
    return prior, final


def metrics(y, p):
    return {"logloss": round(log_loss(y, p), 4), "brier": round(brier_score_loss(y, p), 4), "auc": round(roc_auc_score(y, p), 4)}


def calibration(y, p, bins=10):
    q = pd.qcut(p, bins, labels=False, duplicates="drop")
    t = pd.DataFrame({"y": y, "p": p, "q": q}).groupby("q").agg(n=("y", "size"), pred=("p", "mean"), actual=("y", "mean"))
    return [{"n": int(r.n), "pred": round(r.pred, 3), "actual": round(r.actual, 3)} for r in t.itertuples()]


if __name__ == "__main__":
    raw = load_shots(SEASON)
    df = featurize(raw)
    df["date"] = pd.to_datetime(df.date)
    cut = df.date.quantile(0.75)
    train, test = df[df.date <= cut], df[df.date > cut]
    print(f"{SEASON}: {len(df)} shots, {df.player.nunique()} shooters; train {len(train)} (to {cut.date()}), test {len(test)}")

    # baselines
    base_rate = train.made.mean()
    zone_rate = train.groupby("zone", observed=True).made.mean()
    dist_bin = pd.cut(df.dist, [0, 1.5, 3, 4.5, 6, 6.75, 8, 20], labels=False)
    dist_rate = train.assign(b=dist_bin[train.index]).groupby("b").made.mean()
    p_zone = test.zone.astype(str).map(zone_rate.rename(index=str)).astype(float).fillna(base_rate).values
    p_dist = pd.Series(dist_bin[test.index]).map(dist_rate).fillna(base_rate).values.astype(float)

    # base model, out-of-fold residuals on train for the shooter feature
    from sklearn.model_selection import GroupKFold
    oof = np.zeros(len(train))
    for tr, va in GroupKFold(5).split(train, groups=train.game):
        m = make_model().fit(train.iloc[tr][FEATURES], train.iloc[tr].made)
        oof[va] = m.predict_proba(train.iloc[va][FEATURES])[:, 1]
    base = make_model().fit(train[FEATURES], train.made)
    p_base_test = base.predict_proba(test[FEATURES])[:, 1]

    # shooter feature: sequential over the whole season, residuals from OOF (train) and from the base model (test, using earlier shots only)
    resid_all = np.concatenate([train.made.values - oof, test.made.values - p_base_test])
    prior_all, effects = shooter_effects(pd.concat([train, test]), resid_all)
    train = train.assign(shooter=prior_all[:len(train)]); test = test.assign(shooter=prior_all[len(train):])
    FEAT2 = FEATURES + ["shooter"]
    aug = HistGradientBoostingClassifier(**{**make_model().get_params(), "categorical_features": [FEAT2.index("zone")]}).fit(train[FEAT2], train.made)
    p_aug_test = aug.predict_proba(test[FEAT2])[:, 1]

    res = {"constant": metrics(test.made, np.full(len(test), base_rate)), "zone_fg": metrics(test.made, p_zone), "distance_bins": metrics(test.made, p_dist),
           "xfg_context": metrics(test.made, p_base_test), "xfg_context_plus_shooter": metrics(test.made, p_aug_test)}
    print(pd.DataFrame(res).T.to_string())
    use_shooter = res["xfg_context_plus_shooter"]["logloss"] < res["xfg_context"]["logloss"]
    chosen = "xfg_context_plus_shooter" if use_shooter else "xfg_context"
    p_final_test = p_aug_test if use_shooter else p_base_test
    cal = calibration(test.made.values, p_final_test)
    print("calibration (test deciles):"); print(pd.DataFrame(cal).to_string(index=False))

    # refit the chosen model on the full season for deployment
    full = pd.concat([train, test])
    if use_shooter:
        final = HistGradientBoostingClassifier(**{**make_model().get_params(), "categorical_features": [FEAT2.index("zone")]}).fit(full[FEAT2], full.made)
        feats = FEAT2
    else:
        final = make_model().fit(full[FEATURES], full.made); feats = FEATURES
    # feature importance by permutation on the test set
    from sklearn.inspection import permutation_importance
    pi = permutation_importance(aug if use_shooter else base, test[feats], test.made, scoring="neg_log_loss", n_repeats=5, random_state=SEED)
    importance = sorted(zip(feats, pi.importances_mean.round(4)), key=lambda t: -t[1])

    os.makedirs(OUT, exist_ok=True)
    joblib.dump({"model": final, "features": feats, "categories": {"zone": list(df.zone.cat.categories)}, "k_shrink": K_SHRINK, "trained_on": SEASON}, os.path.join(OUT, "xfg_model.joblib"))
    effects.to_parquet(os.path.join(OUT, f"shooter_effects_{SEASON}.parquet"), index=False)
    card = {"model": "xFG (expected field goal)", "version": datetime.date.today().isoformat(), "trained_on": SEASON, "n_shots": int(len(df)), "n_shooters": int(df.player.nunique()),
            "split": f"time-based, test = games after {cut.date()} ({len(test)} shots)", "features": feats, "chosen": chosen, "metrics_test": res,
            "calibration_test": cal, "permutation_importance": importance, "shooter_shrinkage_k": K_SHRINK,
            "algorithm": "sklearn HistGradientBoostingClassifier, early stopping", "notes": "Shooter effect is a sequential shrunk residual computed from earlier shots only; no leakage."}
    json.dump(card, open(os.path.join(OUT, "model_card.json"), "w"), indent=1)
    print(f"\nchosen: {chosen}; saved model, card and {len(effects)} shooter effects")
    print("top features:", importance[:8])
