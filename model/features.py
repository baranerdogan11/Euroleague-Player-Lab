"""Feature construction shared by training, nightly scoring and the prediction service. No I/O, no DuckDB."""
import numpy as np
import pandas as pd

NUMERIC = ["dist", "angle", "x", "y", "clock_sec", "minute", "margin", "quarter"]
BINARY = ["three", "home"]   # fastbreak / second_chance / points_off_tov are excluded: the feed annotates them on made shots only (label leakage)
CATEG = ["zone"]
FEATURES = NUMERIC + BINARY + CATEG


def featurize(df):
    d = df.copy()
    d["dist"] = np.hypot(d.x, d.y) / 100
    d["angle"] = np.degrees(np.arctan2(d.x.abs(), d.y.clip(lower=1)))
    d["three"] = (d.pts == 3).astype(int)
    d["quarter"] = np.where(d.minute > 40, 5, np.ceil(d.minute / 10)).astype(int)
    mmss = d.clock.fillna("0:00").str.split(":", expand=True)
    d["clock_sec"] = pd.to_numeric(mmss[0], errors="coerce").fillna(0) * 60 + pd.to_numeric(mmss[1], errors="coerce").fillna(0)
    d["home"] = (d.club == d.home).astype(int)
    own = np.where(d.home == 1, d.score_home, d.score_away); opp = np.where(d.home == 1, d.score_away, d.score_home)
    # the feed reports the score after the play, so a made basket must be removed to get the pre-shot margin
    d["margin"] = (pd.Series(own, index=d.index).fillna(0) - pd.Series(opp, index=d.index).fillna(0) - d.made.astype(int) * d.pts).astype(float)
    for c in BINARY:
        d[c] = d[c].astype(int)
    d["zone"] = d.zone.fillna("?").astype("category")
    d["made"] = d.made.astype(int)
    return d
