"""Expected field-goal model (xFG): the probability a shot goes in given where and when it was taken.

Trained on past seasons' warehouses (model/training.json lists them, oldest first). Context features only in
the base model (location, distance, angle, shot value, clock, game state, transition flags); shooter quality
enters as a separate, leak-free feature: each shooter's shrunk residual (made minus xFG) accumulated over his
earlier shots only, decayed at each new season exactly as model/score.py decays last season's effects. Validation
is by time: the last 25% of the latest season's games are held out, everything before them trains. Outputs the
fitted model, a model card with metrics and calibration, and per-shooter effects (as of the end of the latest
season) for use as priors next season.

usage: python model/xfg.py                          # seasons from model/training.json
       python model/xfg.py E2022 E2023 E2024 E2025  # explicit list, oldest first
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "model")
SEASONS = [a for a in sys.argv[1:] if a.startswith("E")] or json.load(open(os.path.join(OUT, "training.json")))["seasons"]
SEASON = SEASONS[-1]   # the latest training season: validation, shooter effects and the model card's trained_on
K_SHRINK = 150.0       # attempts at which a shooter's own record gets half the weight of the league prior
PRIOR_DECAY = 0.6      # a shooter's record carried into a new season keeps this share of its weight (rosters and roles change)
SEED = 7

from features import NUMERIC, BINARY, CATEG, FEATURES, featurize  # noqa: E402


def load_shots(season):
    con = duckdb.connect()
    w = os.path.join(ROOT, "warehouse", season)
    ctx = os.path.join(w, "shot_context.parquet")
    has_ctx = os.path.exists(ctx)
    q = f"""
    select s.game, s.seq, s.player, s.club, s.x, s.y, s.made, s.pts, s.zone, s.minute, s.clock, s.fastbreak, s.second_chance, s.points_off_tov,
           s.score_home, s.score_away, g.date, g.home, g.away, g.round,
           {"c.poss_sec, c.poss_start" if has_ctx else "null::integer as poss_sec, null::varchar as poss_start"}
    from read_parquet('{w}/shots.parquet') s join read_parquet('{w}/games.parquet') g using (game)
    {f"left join read_parquet('{ctx}') c using (game, seq)" if has_ctx else ""}
    order by g.date, s.game, s.minute, s.seq"""
    return con.execute(q).df()


def load_seasons(seasons):
    """Shots of several seasons, oldest first; game codes restart every season, so (season, game) is the key."""
    return pd.concat([load_shots(s).assign(season=s) for s in seasons], ignore_index=True)


def make_model(seed=SEED):
    return HistGradientBoostingClassifier(learning_rate=0.05, max_iter=600, max_leaf_nodes=31, min_samples_leaf=40, l2_regularization=1.0,
                                          early_stopping=True, validation_fraction=0.1, n_iter_no_change=40, categorical_features=[FEATURES.index(c) for c in CATEG],
                                          random_state=seed)


def shooter_effects(df, resid, k=K_SHRINK, decay=PRIOR_DECAY):
    """Sequential shrunk residual per shooter: uses only shots before each shot (leak-free feature). At each new
    season every running record is decayed, as model/score.py does with last season's effects."""
    prior = np.zeros(len(df))
    acc, n = {}, {}
    seasons = df.season.values if "season" in df else np.zeros(len(df))
    for i, (p, r) in enumerate(zip(df.player.values, resid)):
        if i and seasons[i] != seasons[i - 1]:
            acc = {q: v * decay for q, v in acc.items()}; n = {q: v * decay for q, v in n.items()}
        prior[i] = acc.get(p, 0.0) / (n.get(p, 0) + k)
        acc[p] = acc.get(p, 0.0) + r; n[p] = n.get(p, 0) + 1
    final = pd.DataFrame({"player": list(acc), "n": [round(float(n[p]), 1) for p in acc], "effect": [acc[p] / (n[p] + k) for p in acc]})
    return prior, final


def metrics(y, p):
    return {"logloss": round(log_loss(y, p), 4), "brier": round(brier_score_loss(y, p), 4), "auc": round(roc_auc_score(y, p), 4)}


def calibration(y, p, bins=10):
    q = pd.qcut(p, bins, labels=False, duplicates="drop")
    t = pd.DataFrame({"y": y, "p": p, "q": q}).groupby("q").agg(n=("y", "size"), pred=("p", "mean"), actual=("y", "mean"))
    return [{"n": int(r.n), "pred": round(r.pred, 3), "actual": round(r.actual, 3)} for r in t.itertuples()]


if __name__ == "__main__":
    raw = load_seasons(SEASONS)
    df = featurize(raw)
    df["date"] = pd.to_datetime(df.date)
    df["gkey"] = df.season + "/" + df.game.astype(str)
    cut = df[df.season == SEASON].date.quantile(0.75)
    held = (df.season == SEASON) & (df.date > cut)
    train, test = df[~held], df[held]
    by_season = {s: int(n) for s, n in df.groupby("season").size().items()}
    print(f"{'+'.join(SEASONS)}: {len(df)} shots {by_season}, {df.player.nunique()} shooters; train {len(train)} (to {cut.date()}), test {len(test)} ({SEASON})")

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
    for tr, va in GroupKFold(5).split(train, groups=train.gkey):
        m = make_model().fit(train.iloc[tr][FEATURES], train.iloc[tr].made)
        oof[va] = m.predict_proba(train.iloc[va][FEATURES])[:, 1]
    base = make_model().fit(train[FEATURES], train.made)
    p_base_test = base.predict_proba(test[FEATURES])[:, 1]
    # the same context model fitted on the latest season's training games only (the setup before multi-season training)
    last = train[train.season == SEASON]
    p_last_test = make_model().fit(last[FEATURES], last.made).predict_proba(test[FEATURES])[:, 1] if len(SEASONS) > 1 else p_base_test

    # shooter feature: sequential over the whole season, residuals from OOF (train) and from the base model (test, using earlier shots only)
    resid_all = np.concatenate([train.made.values - oof, test.made.values - p_base_test])
    prior_all, effects = shooter_effects(pd.concat([train, test]), resid_all)
    train = train.assign(shooter=prior_all[:len(train)]); test = test.assign(shooter=prior_all[len(train):])
    FEAT2 = FEATURES + ["shooter"]
    aug = HistGradientBoostingClassifier(**{**make_model().get_params(), "categorical_features": [FEAT2.index(c) for c in CATEG]}).fit(train[FEAT2], train.made)
    p_aug_test = aug.predict_proba(test[FEAT2])[:, 1]

    res = {"constant": metrics(test.made, np.full(len(test), base_rate)), "zone_fg": metrics(test.made, p_zone), "distance_bins": metrics(test.made, p_dist),
           "xfg_context_latest_season_only": metrics(test.made, p_last_test), "xfg_context": metrics(test.made, p_base_test), "xfg_context_plus_shooter": metrics(test.made, p_aug_test)}
    print(pd.DataFrame(res).T.to_string())
    use_shooter = res["xfg_context_plus_shooter"]["logloss"] < res["xfg_context"]["logloss"]
    chosen = "xfg_context_plus_shooter" if use_shooter else "xfg_context"
    p_final_test = p_aug_test if use_shooter else p_base_test
    cal = calibration(test.made.values, p_final_test)
    print("calibration (test deciles):"); print(pd.DataFrame(cal).to_string(index=False))

    # refit the chosen model on the full season for deployment
    full = pd.concat([train, test])
    if use_shooter:
        final = HistGradientBoostingClassifier(**{**make_model().get_params(), "categorical_features": [FEAT2.index(c) for c in CATEG]}).fit(full[FEAT2], full.made)
        feats = FEAT2
    else:
        final = make_model().fit(full[FEATURES], full.made); feats = FEATURES
    # feature importance by permutation on the test set
    from sklearn.inspection import permutation_importance
    pi = permutation_importance(aug if use_shooter else base, test[feats], test.made, scoring="neg_log_loss", n_repeats=5, random_state=SEED)
    importance = sorted(zip(feats, pi.importances_mean.round(4)), key=lambda t: -t[1])

    os.makedirs(OUT, exist_ok=True)
    joblib.dump({"model": final, "features": feats, "categories": {"zone": list(df.zone.cat.categories), "poss_start": list(df.poss_start.cat.categories)}, "k_shrink": K_SHRINK, "trained_on": SEASON, "training_seasons": SEASONS}, os.path.join(OUT, "xfg_model.joblib"))
    effects.to_parquet(os.path.join(OUT, f"shooter_effects_{SEASON}.parquet"), index=False)
    card = {"model": "xFG (expected field goal)", "version": datetime.date.today().isoformat(), "trained_on": SEASON, "training_seasons": SEASONS, "n_shots": int(len(df)),
            "n_shots_by_season": by_season, "n_shooters": int(df.player.nunique()),
            "split": f"time-based, test = {SEASON} games after {cut.date()} ({len(test)} shots), train = every earlier game of {', '.join(SEASONS)}", "features": feats, "chosen": chosen, "metrics_test": res,
            "calibration_test": cal, "permutation_importance": importance, "shooter_shrinkage_k": K_SHRINK,
            "algorithm": "sklearn HistGradientBoostingClassifier, early stopping", "notes": "Shooter effect is a sequential shrunk residual computed from earlier shots only, decayed by PRIOR_DECAY at each new season; no leakage.",
            "shooter_prior_decay": PRIOR_DECAY,
            "changes": "Trained on several seasons instead of one (model/training.json); the context model fitted on the latest season alone is kept as a comparison row in metrics_test.",
            "context_coverage": round(float(df.poss_sec.notna().mean()), 3)}
    json.dump(card, open(os.path.join(OUT, "model_card.json"), "w"), indent=1)
    print(f"\nchosen: {chosen}; saved model, card and {len(effects)} shooter effects")
    print("top features:", importance[:8])
