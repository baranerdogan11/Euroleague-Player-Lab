"""Gold layer: per-club site files and index.html, produced by SQL over the warehouse (warehouse/<season>/).

A club's page lists its active roster stints; each player's games, box lines and shots come from every club
he played for this season, so a mid-season move keeps his full record under his current club.
Photos (photos/*.webp) and crests (logos/*.png) are referenced by path. Run after warehouse.py.

usage: python build.py E2026
"""
import datetime
import glob
import json
import os
import sys
import duckdb

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2026"
ROOT = os.path.dirname(os.path.abspath(__file__))
W = os.path.join(ROOT, "warehouse", SEASON)
OUT = os.path.join(ROOT, "teams", SEASON)
os.makedirs(OUT, exist_ok=True)
for stale in glob.glob(os.path.join(OUT, "*.json")):
    if os.path.basename(stale) not in ("monitor.json",):      # club files are regenerated; the monitoring snapshot is owned by monitor.py
        os.remove(stale)
label = lambda s: f"{s[1:]}-{str(int(s[1:]) + 1)[2:]}"
STAT_KEYS = ["pts", "fgm2", "fga2", "fgm3", "fga3", "ftm", "fta", "oreb", "dreb", "reb", "ast", "stl", "tov", "blk", "blka", "pf", "fd", "pir"]

con = duckdb.connect()
for t in ["clubs", "players", "roster_stints", "games", "box", "shots"]:
    con.execute(f"create view {t} as select * from read_parquet('{os.path.join(W, t + '.parquet')}')")
xfg_path = os.path.join(W, "shots_xfg.parquet")
HAS_XFG = os.path.exists(xfg_path)
con.execute(f"create view shots_xfg as select * from read_parquet('{xfg_path}')" if HAS_XFG else "create view shots_xfg as select null::int game, null::int seq, null::varchar player, null::double xfg where false")
prof_path = os.path.join(W, "player_shooting.parquet")
PROFILES = {}
if os.path.exists(prof_path):
    import pandas as pd
    pf = pd.read_parquet(prof_path)
    if "att" in pf.columns and len(pf):
        PROFILES = {r.player: r for r in pf.itertuples(index=False)}
notes_path = os.path.join(W, "notes.parquet")
NOTES = {}
if os.path.exists(notes_path):
    import pandas as pd
    nf = pd.read_parquet(notes_path)
    NOTES = {r.player: r for r in nf.itertuples(index=False) if r.status == "ok"}
priors_path = os.path.join(ROOT, "model", "shooting_priors.json")
PRIORS = json.load(open(priors_path)) if os.path.exists(priors_path) else None
rows = lambda q, *a: [dict(zip([d[0] for d in con.description], r)) for r in con.execute(q, a).fetchall()]

def note_of(player):
    n = NOTES.get(player)
    if n is None:
        return None
    return {"text": n.note, "generated_at": n.generated_at[:10], "model": n.model, "confidence": n.confidence, "key_numbers": json.loads(n.key_numbers) if n.key_numbers else []}


def profile_of(player, gidx):
    pr = PROFILES.get(player)
    if pr is None:
        return None
    curve = [[gidx[c[0]], c[1], c[2], c[3], c[4]] for c in pr.curve if c[0] in gidx]
    g = lambda k: (None if pd.isna(getattr(pr, k, None)) else float(getattr(pr, k))) if hasattr(pr, k) else None
    return {"att": int(pr.att), "quality": pr.quality, "quality_shrunk": pr.quality_shrunk, "quality_pct": pr.quality_pct, "quality_pct_lo": g("quality_pct_lo"), "quality_pct_hi": g("quality_pct_hi"),
            "skill": pr.skill, "skill_shrunk": pr.skill_shrunk, "skill_sd": pr.skill_sd, "skill_pct": pr.skill_pct, "skill_pct_lo": g("skill_pct_lo"), "skill_pct_hi": g("skill_pct_hi"), "pae": pr.pae, "curve": curve}


# Broadcast colourways: base tints panels and the hero wedge, accent carries text, marks and controls on a dark ground.
PALETTES = {"IST": ("#002D74", "#00A7E1"), "MIL": ("#8E1610", "#F0342B"), "BES": ("#2A2A2A", "#FFFFFF"), "RED": ("#A3121A", "#FF3B44"), "DUB": ("#003E2E", "#F6881F"),
            "BAR": ("#023485", "#EDBB00"), "MUN": ("#8F0F25", "#FF4D6D"), "ULK": ("#004280", "#FFED00"), "HTA": ("#9E1218", "#FF3B44"), "BAS": ("#0A2240", "#E4213C"),
            "ASV": ("#2A2A2A", "#FFFFFF"), "TEL": ("#2371B5", "#FFF100"), "OLY": ("#9B0A18", "#F03A4A"), "PAN": ("#0B6B3A", "#22D37A"), "PRS": ("#2A2A2A", "#FFFFFF"),
            "PAR": ("#2A2A2A", "#FFFFFF"), "MAD": ("#0B3F8F", "#FEBE10"), "PAM": ("#0A3792", "#FF6C0E"), "VIR": ("#2A2A2A", "#FFFFFF"), "ZAL": ("#0C6F3E", "#4ADE80")}
DEFAULT_PALETTE = ("#1F2B47", "#F26F21")

clubs = rows("select * from clubs order by name")
for c in clubs:
    c["logo"] = f"logos/{c['club']}.png" if os.path.exists(os.path.join(ROOT, "logos", f"{c['club']}.png")) else None
summary = []
collected = {}
for c in clubs:
    code = c["club"]
    roster = rows("""select s.player, p.name, s.dorsal, s.position, p.height_cm, p.birth_date, p.country
                     from roster_stints s join players p using (player) where s.club = ? and s.active
                     order by try_cast(s.dorsal as integer) nulls last, p.name""", code)
    players = []
    for r in roster:
        lines = rows("""select b.*, g.round, g.phase, g.date, g.home, g.away, g.home_score, g.away_score
                        from box b join games g using (game) where b.player = ? and b.minutes > 0 order by g.date, g.game""", r["player"])
        gidx = {b["game"]: i for i, b in enumerate(lines)}
        tot = {k: sum(b[k] or 0 for b in lines) for k in STAT_KEYS}
        tot["min"] = round(sum(b["minutes"] for b in lines), 1); tot["gp"] = len(lines)
        log = [[gidx[b["game"]], round(b["minutes"], 1), b["pts"], b["reb"], b["ast"], b["stl"], b["blk"], b["tov"], b["fgm2"], b["fga2"], b["fgm3"], b["fga3"], b["ftm"], b["fta"], b["pir"], b["plusminus"]] for b in lines]
        # shot columns: 9 = expectation for a league-average shooter (context only), 10 = the shooter-aware probability; every
        # "expected" figure on the page uses column 9 so the season stats, the profile panel and the note agree
        sh = rows("""select s.game, s.x, s.y, s.made, s.pts, s.minute, s.zone, s.fastbreak, s.second_chance, x.xfg_ctx, x.xfg
                     from shots s left join shots_xfg x using (game, seq) where s.player = ? order by s.game, s.minute, s.seq""", r["player"])
        rnd = lambda v: round(v, 3) if v is not None else None
        shots = [[gidx[s["game"]], s["x"], s["y"], int(s["made"]), s["pts"], s["minute"], s["zone"], int(s["fastbreak"]), int(s["second_chance"]), rnd(s["xfg_ctx"]), rnd(s["xfg"])] for s in sh if s["game"] in gidx]
        scored = [s for s in shots if s[9] is not None]
        xfg = {"att": len(scored), "xfg": round(sum(s[9] for s in scored) / len(scored), 4) if scored else None,
               "xpts": round(sum(s[9] * s[4] for s in scored), 2), "pts": sum(s[3] * s[4] for s in scored)} if scored else None
        games = [{"code": b["game"], "round": b["round"], "date": str(b["date"]), "home": b["home"], "away": b["away"], "hs": b["home_score"], "as": b["away_score"], "phase": b["phase"], "own": b["club"]} for b in lines]
        players.append({"pid": "P" + r["player"], "name": r["name"], "dorsal": r["dorsal"], "position": r["position"], "height": r["height_cm"],
                        "birth": str(r["birth_date"]) if r["birth_date"] else None, "country": r["country"],
                        "photo": f"photos/{r['player']}.webp" if os.path.exists(os.path.join(ROOT, "photos", f"{r['player']}.webp")) else None,
                        "cur": {"tot": tot, "log": log, "shots": shots, "games": games, "xfg": xfg, "profile": profile_of(r["player"], gidx), "note": note_of(r["player"])}})
    collected[code] = players

# league percentiles among rotation players (3+ games, 10+ minutes a game), per game and per 40 minutes; turnovers inverted so higher is better
COUNTING = ("pts", "reb", "ast", "stl", "blk", "tov", "pir")
def per_game(tot, per40=False):
    gp = tot["gp"] or 1
    fga = tot["fga2"] + tot["fga3"]
    scale = (40 / tot["min"]) if per40 and tot["min"] else (1 / gp)
    return {**{k: tot[k] * scale for k in COUNTING},
            "fg2": tot["fgm2"] / tot["fga2"] if tot["fga2"] >= 15 else None, "fg3": tot["fgm3"] / tot["fga3"] if tot["fga3"] >= 15 else None,
            "ft": tot["ftm"] / tot["fta"] if tot["fta"] >= 10 else None, "ts": tot["pts"] / (2 * (fga + 0.44 * tot["fta"])) if fga else None}
eligible = lambda tot: tot["gp"] >= 3 and tot["min"] / tot["gp"] >= 10
pools = {False: [], True: []}
for ps in collected.values():
    for p in ps:
        if eligible(p["cur"]["tot"]):
            pools[False].append(per_game(p["cur"]["tot"])); pools[True].append(per_game(p["cur"]["tot"], True))
league_n = len(pools[False])
def percentiles(tot, per40=False):
    if league_n < 20 or not eligible(tot):
        return None
    me = per_game(tot, per40); out = {}
    for k, v in me.items():
        if v is None:
            out[k] = None; continue
        vals = [r[k] for r in pools[per40] if r[k] is not None]
        below = sum(1 for x in vals if (x > v if k == "tov" else x < v))
        out[k] = round(100 * below / len(vals))
    return out


def zone_of(x, y, pts):
    d = (x * x + y * y) ** 0.5
    if pts == 3:
        return "c3" if y < 141.5 else "a3"
    if d < 150:
        return "rim"
    if abs(x) < 245 and y < 422.5:
        return "paint"
    return "mid"


def league_refs(season):
    """League FG% and points per attempt by zone, and the shooting splits, from a season's warehouse. None while the season is thin."""
    w = os.path.join(ROOT, "warehouse", season)
    if not all(os.path.exists(os.path.join(w, t + ".parquet")) for t in ("shots", "box")):
        return None
    sh = con.execute(f"select x, y, pts, made::int from read_parquet('{os.path.join(w, 'shots.parquet')}')").fetchall()
    if len(sh) < 3000:
        return None
    acc = {k: [0, 0, 0] for k in ("rim", "paint", "mid", "c3", "a3")}
    for x, y, pts, made in sh:
        z = acc[zone_of(x, y, pts)]; z[0] += 1; z[1] += made; z[2] += made * pts
    acc["three"] = [acc["c3"][i] + acc["a3"][i] for i in range(3)]
    zones = {k: {"att": a, "fg": round(m / a, 4), "ppa": round(p / a, 3)} for k, (a, m, p) in acc.items()}
    fgm2, fga2, fgm3, fga3, ftm, fta, pts = con.execute(f"select sum(fgm2), sum(fga2), sum(fgm3), sum(fga3), sum(ftm), sum(fta), sum(pts) from read_parquet('{os.path.join(w, 'box.parquet')}')").fetchone()
    splits = {"fg2": round(fgm2 / fga2, 4), "fg3": round(fgm3 / fga3, 4), "ft": round(ftm / fta, 4), "ts": round(pts / (2 * (fga2 + fga3 + 0.44 * fta)), 4)}
    return {"season": season, "shots": len(sh), "zones": zones, "splits": splits}


league = league_refs(SEASON) or (league_refs(PRIORS["reference_season"]) if PRIORS else None)
for code, players in collected.items():
    for p in players:
        tot = p["cur"]["tot"]
        p["cur"]["pct"] = percentiles(tot)
        p["cur"]["pct40"] = percentiles(tot, True)
        p["cur"]["per40"] = {k: round(tot[k] * 40 / tot["min"], 1) for k in COUNTING} if tot["min"] else None
    played = con.execute("select count(*) from games where played and ? in (home, away)", [code]).fetchone()[0]
    upcoming = rows("select game as code, round, cast(date as varchar) as date, home, away, phase from games where not played and ? in (home, away) order by date limit 3", code)
    json.dump({"code": code, "season": SEASON, "label": label(SEASON), "games_played": played, "upcoming": upcoming, "players": players, "real_code": code},
              open(os.path.join(OUT, f"{code}.json"), "w"), separators=(",", ":"), ensure_ascii=False)
    summary.append((code, len(players), played, sum(len(p["cur"]["shots"]) for p in players)))

status_path = os.path.join(W, "status.json")
status = json.load(open(status_path)) if os.path.exists(status_path) else None
if status:
    json.dump(status, open(os.path.join(OUT, "status.json"), "w"), indent=1)
card_path = os.path.join(ROOT, "model", "model_card.json")
card = json.load(open(card_path)) if os.path.exists(card_path) else None
meta = {"season": SEASON, "label": label(SEASON), "model": {"version": card["version"], "trained_on": card["trained_on"], "logloss": card["metrics_test"][card["chosen"]]["logloss"],
                                                           "auc": card["metrics_test"][card["chosen"]]["auc"], "n_shots": card["n_shots"]} if card else None, "clubs": [{"code": c["club"], "name": c["name"], "short": c["short"], "country": c["country"], "city": c["city"], "logo": c["logo"], "base": PALETTES.get(c["club"], DEFAULT_PALETTE)[0], "accent": PALETTES.get(c["club"], DEFAULT_PALETTE)[1]} for c in clubs],
        "league_n": league_n, "pool_rule": "3+ games, 10+ minutes a game", "league": league,
        "priors": {"league_quality": PRIORS["league_quality"], "k_skill": PRIORS["k_skill"], "k_quality": PRIORS["k_quality"], "reference_season": PRIORS["reference_season"],
                   "tau_skill": PRIORS["tau_skill"]} if PRIORS else None,
        "built": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"), "path": f"teams/{SEASON}/",
        "status": {k: status.get(k) for k in ("checked_at", "games", "shots", "players", "tests", "ok", "failures", "warnings")} if status else None}
json.dump(meta, open(os.path.join(OUT, "index.json"), "w"), ensure_ascii=False)
tpl = open(os.path.join(ROOT, "template.html"), encoding="utf-8").read()
open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(tpl.replace("/*META*/", json.dumps(meta, ensure_ascii=False)))
for s in summary:
    print("%-4s players %2d  games %2d  shots %4d" % s)
print("index.html + teams/%s/*.json written from warehouse" % SEASON)
