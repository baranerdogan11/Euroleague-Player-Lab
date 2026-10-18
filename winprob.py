"""Win probability from the play-by-play: the chance the home club wins, at every moment of a game.

The final margin is treated as the current margin plus what is still to come, and what is still to come grows with the
time left: on average a few points for the home court, the stronger club and the club with the ball, with a spread that
shrinks as the clock runs down (the random-walk model behind most published basketball win probability charts, Stern 1994).
With f the share of a 40-minute game still to play (overtime counts its own five minutes) the model is a logistic
regression without intercept on four features:
  margin / sqrt(f)          home score minus away score
  sqrt(f)                   the home court
  strength * sqrt(f)        pregame strength: each club's average margin in its earlier games this season, shrunk towards
                            zero by SHRINK games (home minus away)
  ball / sqrt(f)            +1 home ball, -1 away ball, 0 when the ball is loose or the period has not started
f has a floor of F_MIN so a tied game at the buzzer stays at 50% and the next state comes from overtime.

Trained on every game of the seasons in TRAIN (one state per event, each game weighted equally); the coefficients and the
fit go to model/winprob.json, which build.py reads to draw each game page's chart.

usage: python winprob.py          fit on TRAIN, validate on this season's games so far, write model/winprob.json
"""
import json
import math
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
TRAIN = ["E2025"]                 # seasons with the full play-by-play in warehouse/ (older seasons keep only shots)
TEST = "E2026"
SHRINK = 5                        # pregame strength: margin sum / (games + SHRINK)
F_MIN = 2 / 2400                  # two seconds
STEP = 10                         # the game page samples the curve every STEP seconds of game time
MODEL = os.path.join(ROOT, "model", "winprob.json")
FEATURES = ["margin", "home", "strength", "ball"]


def elapsed(period, clock_sec):
    """Seconds of game time played at an event: 10-minute quarters, 5-minute overtimes."""
    if period <= 4:
        return (period - 1) * 600 + (600 - clock_sec)
    return 2400 + (period - 5) * 300 + (300 - clock_sec)


def length(periods):
    return 2400 + 300 * max(0, periods - 4)


def left(period, clock_sec):
    """Share of a 40-minute game still to be played before the current period's buzzer could end it."""
    return max(F_MIN, (clock_sec + (600 * (4 - period) if period <= 4 else 0)) / 2400)


def states(evs, home, away):
    """(elapsed seconds, period, clock seconds, margin, ball) after each timed event of one game, in game-clock order (the
    feed appends late corrections with a later sequence number, so feed order alone can run backwards in time).
    evs: dicts with seq, period, club, playtype, clock_sec, score_home, score_away (the events table)."""
    h = a = 0
    ball = 0
    opp = {home: away, away: home}
    side = {home: 1, away: -1}
    out = []
    when = lambda e: (e["period"], -(e["clock_sec"] if e["clock_sec"] is not None else 601 if e["playtype"] == "BP" else -1), e["seq"])
    for e in sorted(evs, key=when):
        pt, c, per, cs = e["playtype"], e["club"], e["period"], e["clock_sec"]
        # the feed prints the running score on scoring plays only, and a club still on 0 as null; scores never go down
        h, a = max(h, e["score_home"] or 0), max(a, e["score_away"] or 0)
        if pt in ("BP", "EP"):
            ball = 0
        elif c in side:
            if pt in ("2FGM", "3FGM", "FTM", "TO"):
                ball = side[opp[c]]
            elif pt in ("D", "O", "ST", "JB"):
                ball = side[c]
        if cs is None:
            continue
        out.append((elapsed(per, cs), per, cs, h - a, ball))
    return out


def features(margin, f, strength, ball):
    r = math.sqrt(f)
    return [margin / r, r, strength * r, ball / r]


def prob(coef, margin, f, strength, ball):
    z = sum(c * x for c, x in zip(coef, features(margin, f, strength, ball)))
    return 1 / (1 + math.exp(-max(-40, min(40, z))))


def strengths(games):
    """{game: home strength minus away strength} from each club's earlier games, in date order.
    games: dicts with game, date_utc, home, away, home_score, away_score (played games)."""
    tot, n, out = {}, {}, {}
    s = lambda c: tot.get(c, 0) / (n.get(c, 0) + SHRINK)
    for g in sorted(games, key=lambda g: (g["date_utc"], g["game"])):
        out[g["game"]] = s(g["home"]) - s(g["away"])
        m = g["home_score"] - g["away_score"]
        for c, v in ((g["home"], m), (g["away"], -m)):
            tot[c], n[c] = tot.get(c, 0) + v, n.get(c, 0) + 1
    return out


def curve(coef, evs, game):
    """The game page's chart: home win probability in per mille (v) and the home margin (m) every STEP seconds of game time,
    from tip-off (the pregame figure) to the final buzzer (1000 or 0). game: dict with home, away, home_score, away_score and strength."""
    S = states(evs, game["home"], game["away"])
    if not S:
        return None
    periods = max(4, max(s[1] for s in S))
    end = length(periods)
    pts, mg, i, last = [], [], 0, (0, 1, 600, 0, 0)
    for t in range(0, end, STEP):
        while i < len(S) and S[i][0] <= t:
            last = S[i]
            i += 1
        _, per, cs, m, ball = last
        # between the previous event and t the clock ran on: the share left comes from t itself, in the period t falls in
        tp = min(periods, 1 + t // 600) if t < 2400 else 5 + (t - 2400) // 300
        tcs = (600 - t % 600) if t < 2400 else (300 - (t - 2400) % 300)
        if tp != per:
            ball = 0
        pts.append(round(1000 * prob(coef, m, left(tp, tcs), game["strength"], ball)))
        mg.append(m)
    pts.append(1000 if game["home_score"] > game["away_score"] else 0)
    mg.append(game["home_score"] - game["away_score"])
    return {"step": STEP, "len": end, "v": pts, "m": mg}


def load():
    return json.load(open(MODEL)) if os.path.exists(MODEL) else None


def _season(con, season):
    w = os.path.join(ROOT, "warehouse", season)
    games = [dict(zip(("game", "date_utc", "home", "away", "home_score", "away_score"), r)) for r in con.execute(
        f"select game, date_utc, home, away, home_score, away_score from read_parquet('{w}/games.parquet') where played").fetchall()]
    st = strengths(games)
    evs = {}
    for r in con.execute(f"select game, seq, period, club, playtype, clock_sec, score_home, score_away from read_parquet('{w}/events.parquet')").fetchall():
        evs.setdefault(r[0], []).append(dict(zip(("game", "seq", "period", "club", "playtype", "clock_sec", "score_home", "score_away"), r)))
    X, y, w_, gid = [], [], [], []
    for g in games:
        S = states(evs.get(g["game"], []), g["home"], g["away"])
        if not S or S[-1][3] != g["home_score"] - g["away_score"]:   # a feed that does not end on the final score is left out
            continue
        win = int(g["home_score"] > g["away_score"])
        for _, per, cs, m, ball in S:
            X.append(features(m, left(per, cs), st[g["game"]], ball))
            y.append(win)
            w_.append(1 / len(S))
            gid.append(g["game"])
    return X, y, w_, gid


def main():
    import duckdb
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    con = duckdb.connect()
    parts = [_season(con, s) for s in TRAIN]
    X = np.array([r for p in parts for r in p[0]]); y = np.array([v for p in parts for v in p[1]]); w = np.array([v for p in parts for v in p[2]])
    n_games = sum(len(set(p[3])) for p in parts)
    fit = LogisticRegression(fit_intercept=False, C=1e6, max_iter=2000).fit(X, y, sample_weight=w)
    coef = [float(c) for c in fit.coef_[0]]

    def score(X, y, w):
        p = np.clip(1 / (1 + np.exp(-(np.array(X) @ np.array(coef)))), 1e-6, 1 - 1e-6)
        y, w = np.array(y), np.array(w)
        ll = float(-(w * (y * np.log(p) + (1 - y) * np.log(1 - p))).sum() / w.sum())
        br = float((w * (p - y) ** 2).sum() / w.sum())
        bins = []
        for lo in np.arange(0, 1, 0.1):
            k = (p >= lo) & (p < lo + 0.1)
            if k.any():
                bins.append([round(float(lo + 0.05), 2), round(float((w[k] * p[k]).sum() / w[k].sum()), 3), round(float((w[k] * y[k]).sum() / w[k].sum()), 3), int(k.sum())])
        return {"log_loss": round(ll, 4), "brier": round(br, 4), "calibration": bins}

    train = score(X, y, w)
    tx, ty, tw, tg = _season(con, TEST) if os.path.exists(os.path.join(ROOT, "warehouse", TEST, "events.parquet")) else ([], [], [], [])
    test = dict(score(tx, ty, tw), games=len(set(tg))) if tx else None
    out = {"model": "logistic random walk", "features": FEATURES, "coef": [round(c, 5) for c in coef], "shrink": SHRINK, "f_min": F_MIN, "step": STEP,
           "trained_on": TRAIN, "games": n_games, "states": int(len(y)), "train": train, "test": {TEST: test}}
    json.dump(out, open(MODEL, "w"), indent=1)
    print(json.dumps({k: out[k] for k in ("coef", "games", "states")}))
    print("train", {k: train[k] for k in ("log_loss", "brier")}, "test", test and {k: test[k] for k in ("log_loss", "brier", "games")})
    for b in train["calibration"]:
        print("  bin %.2f  predicted %.3f  observed %.3f  n %d" % tuple(b))


if __name__ == "__main__":
    main()
