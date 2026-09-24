"""Shooting profiles: shot quality versus shooting skill, per player, as season curves with shrinkage.

Shot quality  = expected points per attempt of the shots a player takes (xPPA, from xFG).
Shooting skill = points per attempt above expectation (PAE per attempt), i.e. what he adds on top of the
shot quality. Both are noisy over few attempts, so each is shrunk toward the league mean with an empirical
Bayes weight K (in attempts) estimated from a reference season by variance decomposition, and shown with a
posterior standard deviation. Percentiles are against the reference season's distribution of players.

usage: python model/profile.py E2025 --calibrate   # estimates K, league means, reference distribution -> model/shooting_priors.json
       python model/profile.py E2026               # nightly: warehouse/E2026/player_shooting.parquet
"""
import json
import os
import sys
import duckdb
import numpy as np
import pandas as pd

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2026"
CALIBRATE = "--calibrate" in sys.argv
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = os.path.join(ROOT, "warehouse", SEASON)
PRIORS = os.path.join(ROOT, "model", "shooting_priors.json")
MIN_ATT_REF = 100


def load(season):
    w = os.path.join(ROOT, "warehouse", season)
    q = f"""
    select s.game, s.seq, s.player, s.pts, s.made::int as made, x.xfg_ctx as xfg, g.date, g.round   -- context-only expectation: quality of the shot, not of the shooter
    from read_parquet('{w}/shots.parquet') s
    join read_parquet('{w}/shots_xfg.parquet') x using (game, seq)
    join read_parquet('{w}/games.parquet') g using (game)
    order by s.player, g.date, s.game, s.minute, s.seq"""
    return duckdb.query(q).df()


def per_game(df):
    d = df.assign(xpts=df.xfg * df.pts, pts_made=df.made * df.pts)
    g = d.groupby(["player", "game", "date"], as_index=False).agg(att=("made", "size"), xpts=("xpts", "sum"), pts=("pts_made", "sum"), xfg=("xfg", "mean"))
    g["resid"] = g.pts - g.xpts
    return g.sort_values(["player", "date", "game"])


def shot_level_variances(df):
    """Per-shot variance of points scored and of expected points, for the noise term of the decomposition."""
    return float(np.var(df.made * df.pts - df.xfg * df.pts)), float(np.var(df.xfg * df.pts))


def calibrate(df):
    g = per_game(df)
    tot = g.groupby("player").agg(att=("att", "sum"), xpts=("xpts", "sum"), pts=("pts", "sum"))
    tot = tot[tot.att >= MIN_ATT_REF]
    tot["quality"] = tot.xpts / tot.att
    tot["skill"] = (tot.pts - tot.xpts) / tot.att
    shot_var_skill, shot_var_quality = shot_level_variances(df)
    # between-player variance = observed variance of per-player rates minus average sampling noise
    def k_for(col, shot_var):
        noise = float(np.mean(shot_var / tot.att))
        tau2 = max(float(np.var(tot[col])) - noise, 1e-6)
        return shot_var / tau2, tau2
    k_skill, tau2_skill = k_for("skill", shot_var_skill)
    k_quality, tau2_quality = k_for("quality", shot_var_quality)
    # split-half reliability: does the shrunk first-half estimate predict the second half better than the raw one?
    first, second = [], []
    for p, rows in g.groupby("player"):
        if rows.att.sum() < MIN_ATT_REF:
            continue
        half = len(rows) // 2
        a, b = rows.iloc[:half], rows.iloc[half:]
        if a.att.sum() < 30 or b.att.sum() < 30:
            continue
        first.append({"raw": (a.pts.sum() - a.xpts.sum()) / a.att.sum(), "shrunk": (a.pts.sum() - a.xpts.sum()) / (a.att.sum() + k_skill), "att": a.att.sum()})
        second.append((b.pts.sum() - b.xpts.sum()) / b.att.sum())
    f = pd.DataFrame(first); s = np.array(second)
    rel = {"players": int(len(f)), "corr_raw": round(float(np.corrcoef(f.raw, s)[0, 1]), 3), "corr_shrunk": round(float(np.corrcoef(f.shrunk, s)[0, 1]), 3),
           "rmse_raw": round(float(np.sqrt(np.mean((f.raw - s) ** 2))), 4), "rmse_shrunk": round(float(np.sqrt(np.mean((f.shrunk - s) ** 2))), 4),
           "rmse_zero": round(float(np.sqrt(np.mean(s ** 2))), 4)}
    priors = {"reference_season": SEASON, "min_attempts_reference": MIN_ATT_REF, "league_quality": round(float(df.xfg.mul(df.pts).mean()), 4),
              "league_skill": 0.0, "k_skill": round(k_skill, 1), "k_quality": round(k_quality, 1), "shot_var_skill": round(shot_var_skill, 4),
              "shot_var_quality": round(shot_var_quality, 4), "tau_skill": round(float(np.sqrt(tau2_skill)), 4), "tau_quality": round(float(np.sqrt(tau2_quality)), 4),
              "reference_quality": sorted(round(v, 4) for v in (tot.xpts + k_quality * float(df.xfg.mul(df.pts).mean())) / (tot.att + k_quality)),
              "reference_skill": sorted(round(v, 4) for v in (tot.pts - tot.xpts) / (tot.att + k_skill)), "split_half": rel}   # reference players shrunk the same way
    json.dump(priors, open(PRIORS, "w"), indent=1)
    print(f"{SEASON}: {len(tot)} players with >= {MIN_ATT_REF} attempts; league xPPA {priors['league_quality']}")
    print(f"K_skill = {k_skill:.0f} attempts (tau {np.sqrt(tau2_skill):.4f} pts/att), K_quality = {k_quality:.0f} attempts (tau {np.sqrt(tau2_quality):.4f})")
    print("split-half: ", rel)
    return priors


def profiles(df, priors):
    g = per_game(df)
    kq, ks, lq = priors["k_quality"], priors["k_skill"], priors["league_quality"]
    ref_q, ref_s = np.array(priors["reference_quality"]), np.array(priors["reference_skill"])
    pct = lambda ref, v: float((ref < v).mean() * 100) if len(ref) else None
    out = []
    for p, rows in g.groupby("player", sort=False):
        att = rows.att.cumsum().values; xp = rows.xpts.cumsum().values; pt = rows.pts.cumsum().values
        q_sh = (xp + kq * lq) / (att + kq)                       # shrunk shot quality
        s_sh = (pt - xp) / (att + ks)                            # shrunk skill
        s_sd = np.sqrt(priors["shot_var_skill"] / (att + ks))
        q_sd = np.sqrt(priors["shot_var_quality"] / (att + kq))
        n = att[-1]
        out.append({"player": p, "att": int(n), "xfg": round(float((rows.xfg * rows.att).sum() / n), 4),
                    "quality": round(float(xp[-1] / n), 4), "quality_shrunk": round(float(q_sh[-1]), 4), "quality_pct": pct(ref_q, q_sh[-1]),
                    "quality_pct_lo": pct(ref_q, q_sh[-1] - q_sd[-1]), "quality_pct_hi": pct(ref_q, q_sh[-1] + q_sd[-1]),
                    "skill": round(float((pt[-1] - xp[-1]) / n), 4), "skill_shrunk": round(float(s_sh[-1]), 4), "skill_sd": round(float(s_sd[-1]), 4), "skill_pct": pct(ref_s, s_sh[-1]),
                    "skill_pct_lo": pct(ref_s, s_sh[-1] - s_sd[-1]), "skill_pct_hi": pct(ref_s, s_sh[-1] + s_sd[-1]),
                    "pae": round(float(pt[-1] - xp[-1]), 2),
                    "curve": [[int(gm), int(a), round(float(qq), 4), round(float(ss), 4), round(float(sd), 4)] for gm, a, qq, ss, sd in zip(rows.game, att, q_sh, s_sh, s_sd)]})
    return pd.DataFrame(out)


if __name__ == "__main__":
    df = load(SEASON)
    if CALIBRATE:
        calibrate(df)
        sys.exit(0)
    priors = json.load(open(PRIORS))
    out_path = os.path.join(W, "player_shooting.parquet")
    if df.empty:
        pd.DataFrame({"player": pd.Series(dtype=str), "att": pd.Series(dtype=int)}).to_parquet(out_path, index=False)
        print(f"{SEASON}: no shots yet; wrote empty player_shooting.parquet"); sys.exit(0)
    prof = profiles(df, priors)
    prof.to_parquet(out_path, index=False)
    print(f"{SEASON}: profiles for {len(prof)} shooters; K_skill {priors['k_skill']}, K_quality {priors['k_quality']}")
