"""Regularized adjusted plus-minus (RAPM) from the reconstructed stints (lineups.py), the ridge-regression method used for
the NBA (Sill 2010; offence and defence split as in Engelmann's xRAPM).

Every stint gives two observations, one per club on offence: the points it scored per 100 of its possessions (FGA - OREB +
TOV + 0.44 FTA, the site's estimate), explained by an intercept, +1 for each of its five on the floor as attackers and +1
for each of the opposing five as defenders, weighted by the possessions. Ridge regression shrinks every player towards
zero, so a player with little floor time stays close to average; the penalty is picked by cross-validation over games
(each fold holds out whole games). Defensive values are flipped so that higher is better for all three numbers:
  o  points per 100 possessions a player adds to his team's offence, against the average player
  d  points per 100 possessions he takes off the opponent's offence
  t  o + d, his net effect per 100 possessions

usage: python rapm.py E2026        prints the penalty, the fit and the leaders
"""
import os
import sys
import numpy as np

LAMBDAS = (250, 500, 1000, 1500, 2000, 3000, 4000, 6000, 8000, 12000)
FOLDS = 5
MIN_POSS = 20                                  # players with fewer possessions on the floor (offence and defence together) get no value


def observations(con, stints_path):
    """(game, possessions, points per 100, attackers, defenders) for every club on offence in every stint that had possessions."""
    q = f"""select a.game, a.players att, b.players def, a.pts, (a.fga - a.oreb + a.tov + 0.44 * a.fta)::double poss
            from read_parquet('{stints_path}') a join read_parquet('{stints_path}') b on a.game = b.game and a.stint = b.stint and a.club <> b.club
            order by a.game, a.stint, a.club"""
    return [(g, p, 100 * pts / p, att, dfn) for g, att, dfn, pts, p in con.execute(q).fetchall() if p and p > 0]


def design(obs, players):
    idx = {p: i for i, p in enumerate(players)}
    n = len(players)
    X = np.zeros((len(obs), 2 * n))
    for r, (_, _, _, att, dfn) in enumerate(obs):
        for p in att:
            X[r, idx[p]] = 1
        for p in dfn:
            X[r, n + idx[p]] = 1
    return X


def ridge(X, y, w, lam):
    """Weighted ridge with an unpenalised intercept: centre on the weighted means, solve (X'WX + lam I) b = X'Wy."""
    sw = w.sum()
    xm, ym = (w @ X) / sw, (w @ y) / sw
    Xc, yc = X - xm, y - ym
    XtW = Xc.T * w
    b = np.linalg.solve(XtW @ Xc + lam * np.eye(X.shape[1]), XtW @ yc)
    return ym - xm @ b, b


def cv_error(X, y, w, games, lam):
    ug = np.unique(games)
    fold = {g: i % FOLDS for i, g in enumerate(ug)}
    f = np.array([fold[g] for g in games])
    err = 0.0
    for k in range(FOLDS):
        tr, te = f != k, f == k
        a, b = ridge(X[tr], y[tr], w[tr], lam)
        err += float(w[te] @ (y[te] - a - X[te] @ b) ** 2)
    return err / w.sum()


def fit(con, stints_path, lam=None):
    """{player: {"o", "d", "t", "poss"}} plus the chosen penalty and the fitted league rating. None without stints."""
    if not os.path.exists(stints_path):
        return None
    obs = observations(con, stints_path)
    if len(obs) < 200:
        return None
    players = sorted({p for o in obs for p in o[3]} | {p for o in obs for p in o[4]})
    X, y = design(obs, players), np.array([o[2] for o in obs])
    w, games = np.array([o[1] for o in obs]), np.array([o[0] for o in obs])
    cv = None
    if lam is None:
        cv = {l: cv_error(X, y, w, games, l) for l in LAMBDAS}
        lam = min(cv, key=cv.get)
    _, b = ridge(X, y, w, lam)
    n = len(players)
    poss = w @ X                               # possessions on the floor, attacking (first n) and defending (last n)
    out = {}
    for i, p in enumerate(players):
        if poss[i] + poss[n + i] < MIN_POSS:
            continue
        o, d = float(b[i]), -float(b[n + i])
        out[p] = {"o": round(o, 1), "d": round(d, 1), "t": round(o + d, 1), "poss": round(float(poss[i] + poss[n + i]) / 2)}
    return {"players": out, "lambda": lam, "league": round(float(w @ y / w.sum()), 1), "games": int(len(np.unique(games))), "obs": len(obs), "cv": cv}


if __name__ == "__main__":
    import duckdb
    season = sys.argv[1] if len(sys.argv) > 1 else "E2026"
    root = os.path.dirname(os.path.abspath(__file__))
    con = duckdb.connect()
    path = os.path.join(root, "warehouse", season, "stints.parquet")
    res = fit(con, path)
    if not res:
        sys.exit(f"{season}: no stints yet")
    names = dict(con.execute(f"select player, name from read_parquet('{os.path.join(root, 'warehouse', season, 'players.parquet')}')").fetchall())
    print(f"{season}: {res['games']} games, {res['obs']} offensive stints, penalty {res['lambda']}, {len(res['players'])} players")
    ranked = sorted(res["players"].items(), key=lambda kv: -kv[1]["t"])
    for p, v in ranked[:10] + [("...", None)] + ranked[-5:]:
        print(p if v is None else f"{names.get(p, p):28s} {v['t']:+5.1f}  O {v['o']:+5.1f}  D {v['d']:+5.1f}  {v['poss']} poss")
