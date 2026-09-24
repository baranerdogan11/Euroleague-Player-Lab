"""Monitoring: one JSON per night for the status page, plus an append-only run history.

Covers pipeline status and history, data freshness against the schedule, the xFG model's live calibration
by round (log loss, Brier, predicted vs actual make rate) next to the training season as a reference,
shooter-effect coverage, scouting-note acceptance, the serving API's health, and the production model.

usage: python model/monitor.py E2026
"""
import datetime
import json
import os
import sys
import urllib.request
import duckdb
import numpy as np
import pandas as pd

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2026"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = os.path.join(ROOT, "warehouse", SEASON)
OUT_DIR = os.path.join(ROOT, "teams", SEASON)
HISTORY = os.path.join(W, "run_history.jsonl")
API = os.environ.get("XFG_API", "https://euroleague-xfg.onrender.com")
os.makedirs(OUT_DIR, exist_ok=True)
now = datetime.datetime.utcnow()
con = duckdb.connect()


def view(name, season=SEASON):
    p = os.path.join(ROOT, "warehouse", season, name + ".parquet")
    if os.path.exists(p):
        con.execute(f"create or replace view {name}_{season} as select * from read_parquet('{p}')")
        return True
    return False


def rows(q):
    return [dict(zip([d[0] for d in con.description], r)) for r in con.execute(q).fetchall()]


def calibration_by_round(season):
    """Per round: shots, actual make rate, mean xFG, log loss, Brier, and the same for a constant baseline."""
    if not (view("shots", season) and view("shots_xfg", season) and view("games", season)):
        return [], []
    df = con.execute(f"""select g.round, s.made::int made, s.pts, x.xfg, x.xfg_ctx from shots_{season} s join shots_xfg_{season} x using (game, seq)
                         join games_{season} g using (game) where g.phase = 'RS' order by g.round""").df()
    if df.empty:
        return [], []
    base = 0.474
    eps = 1e-6
    out = []
    for r, grp in df.groupby("round"):
        p = grp.xfg.clip(eps, 1 - eps); y = grp.made
        pb = np.full(len(grp), base)
        out.append({"round": int(r), "shots": int(len(grp)), "actual": round(float(y.mean()), 4), "predicted": round(float(grp.xfg.mean()), 4),
                    "pae_ctx": round(float(((y - grp.xfg_ctx) * grp.pts).sum()), 2),
                    "logloss": round(float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()), 4), "brier": round(float(((p - y) ** 2).mean()), 4),
                    "logloss_constant": round(float(-(y * np.log(pb) + (1 - y) * np.log(1 - pb)).mean()), 4)})
    q = pd.qcut(df.xfg, 10, labels=False, duplicates="drop")
    dec = df.assign(q=q).groupby("q").agg(n=("made", "size"), predicted=("xfg", "mean"), actual=("made", "mean"))
    deciles = [{"n": int(a.n), "predicted": round(float(a.predicted), 3), "actual": round(float(a.actual), 3)} for a in dec.itertuples()]
    return out, deciles


# ---- pipeline status and history
status = json.load(open(os.path.join(W, "status.json"))) if os.path.exists(os.path.join(W, "status.json")) else {}
record = {"date": now.strftime("%Y-%m-%d"), "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "ok": status.get("ok"), "games": status.get("games"), "shots": status.get("shots"),
          "players": status.get("players"), "failures": status.get("failures"), "ci": bool(os.environ.get("GITHUB_RUN_ID")), "run_id": os.environ.get("GITHUB_RUN_ID")}
history = [json.loads(l) for l in open(HISTORY)] if os.path.exists(HISTORY) else []
history = [h for h in history if h.get("date") != record["date"]] + [record]
with open(HISTORY, "w") as f:
    for h in history[-120:]:
        f.write(json.dumps(h) + "\n")

# ---- data freshness
freshness = {}
if view("games"):
    g = rows(f"""select count(*) scheduled, sum(played::int) played, max(case when played then date end) last_played_date,
                        min(case when not played then date end) next_game_date,
                        max(case when played then round end) last_round_with_games from games_{SEASON} where phase = 'RS'""")[0]
    by_round = rows(f"select round, count(*) scheduled, sum(played::int) played from games_{SEASON} where phase = 'RS' group by round order by round")
    freshness = {"scheduled": g["scheduled"], "played": g["played"], "last_played_date": str(g["last_played_date"]) if g["last_played_date"] else None,
                 "next_game_date": str(g["next_game_date"]) if g["next_game_date"] else None, "last_round": g["last_round_with_games"],
                 "days_since_last_game": (now.date() - g["last_played_date"]).days if g["last_played_date"] else None,
                 "rounds": [{"round": r["round"], "scheduled": r["scheduled"], "played": r["played"]} for r in by_round]}

# ---- model calibration, live vs training reference
live_rounds, live_deciles = calibration_by_round(SEASON)
card = json.load(open(os.path.join(ROOT, "model", "model_card.json"))) if os.path.exists(os.path.join(ROOT, "model", "model_card.json")) else {}
ref_rounds, ref_deciles = calibration_by_round(card.get("trained_on", "E2025")) if card else ([], [])
live_summary = None
if live_rounds:
    n = sum(r["shots"] for r in live_rounds)
    live_summary = {"shots": n, "logloss": round(sum(r["logloss"] * r["shots"] for r in live_rounds) / n, 4), "brier": round(sum(r["brier"] * r["shots"] for r in live_rounds) / n, 4),
                    "actual": round(sum(r["actual"] * r["shots"] for r in live_rounds) / n, 4), "predicted": round(sum(r["predicted"] * r["shots"] for r in live_rounds) / n, 4),
                    "logloss_constant": round(sum(r["logloss_constant"] * r["shots"] for r in live_rounds) / n, 4),
                    "pae_ctx_per100": round(100 * sum(r["pae_ctx"] for r in live_rounds) / n, 2)}
shooter_cov = None
if view("shots_xfg"):
    eff_path = os.path.join(ROOT, "model", f"shooter_effects_{card.get('trained_on', 'E2025')}.parquet")
    if os.path.exists(eff_path):
        eff = set(pd.read_parquet(eff_path).player)
        sx = con.execute(f"select player from shots_xfg_{SEASON}").df()
        shooter_cov = {"shots": int(len(sx)), "known_shooter_share": round(float(sx.player.isin(eff).mean()), 3) if len(sx) else None}

# ---- scouting notes
notes = None
np_path = os.path.join(W, "notes.parquet")
if os.path.exists(np_path):
    nf = pd.read_parquet(np_path)
    if len(nf):
        reasons = {}
        for c in nf[nf.status != "ok"].checks.dropna():
            for r in json.loads(c):
                key = r.split(":")[0]
                reasons[key] = reasons.get(key, 0) + 1
        by_day = nf.assign(day=nf.generated_at.str[:10]).groupby("day").agg(total=("status", "size"), ok=("status", lambda s: int((s == "ok").sum()))).reset_index()
        notes = {"total": int(len(nf)), "ok": int((nf.status == "ok").sum()), "rejected": int((nf.status != "ok").sum()), "rejection_reasons": reasons,
                 "by_day": [{"day": r.day, "total": int(r.total), "ok": int(r.ok)} for r in by_day.itertuples()], "model": nf.model.iloc[-1]}
eval_path = os.path.join(ROOT, "model", "notes_eval.json")
notes_eval = None
if os.path.exists(eval_path):
    e = json.load(open(eval_path))
    notes_eval = {k: e.get(k) for k in ("n", "auto_pass_rate", "judge_faithfulness_mean", "judge_usefulness_mean", "judge_faithful_5_rate", "unsupported_claims_total", "human_labelled", "judge_human_agreement")}

# ---- serving API
api = {"url": API, "reachable": False}
try:
    t0 = datetime.datetime.utcnow()
    with urllib.request.urlopen(f"{API}/health", timeout=60) as resp:
        body = json.load(resp)
    api.update({"reachable": True, "latency_ms": round((datetime.datetime.utcnow() - t0).total_seconds() * 1000), "model_version": body.get("model_version"), "model_sha256": body.get("model_sha256")})
except Exception as e:
    api["error"] = f"{type(e).__name__}"

# ---- registry
reg_path = os.path.join(ROOT, "model", "registry.json")
registry = json.load(open(reg_path))["models"] if os.path.exists(reg_path) else []
prod = next((m for m in registry if m.get("stage") == "production"), None)
model_info = {"version": card.get("version"), "trained_on": card.get("trained_on"), "n_shots": card.get("n_shots"), "metrics_test": card.get("metrics_test", {}).get(card.get("chosen")),
              "baseline_zone": card.get("metrics_test", {}).get("zone_fg"), "sha256": (prod or {}).get("sha256", "")[:12], "stage": (prod or {}).get("stage"), "registry_entries": len(registry)}

monitor = {"season": SEASON, "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"), "pipeline": {"last": record, "history": history[-60:], "tests": status.get("tests")},
           "freshness": freshness, "calibration": {"live_rounds": live_rounds, "live_deciles": live_deciles, "live_summary": live_summary, "reference_rounds": ref_rounds,
                                                    "reference_deciles": ref_deciles, "reference_season": card.get("trained_on"), "constant_baseline": 0.474},
           "shooter_coverage": shooter_cov, "notes": notes, "notes_eval": notes_eval, "api": api, "model": model_info}
json.dump(monitor, open(os.path.join(OUT_DIR, "monitor.json"), "w"), indent=1)
print(f"monitor: pipeline {'OK' if record['ok'] else 'not OK'} · {freshness.get('played', 0)}/{freshness.get('scheduled', 0)} games played · live shots {live_summary['shots'] if live_summary else 0} · api {'up' if api['reachable'] else 'down'} · notes {notes['ok'] if notes else 0} ok")
