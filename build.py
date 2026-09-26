"""Gold layer: per-club site files and index.html, produced by SQL over the warehouse (warehouse/<season>/).

A club's page lists its active roster stints; each player's games, box lines and shots come from every club
he played for this season, so a mid-season move keeps his full record under his current club.
Photos (photos/*.webp) and crests (logos/*.png) are referenced by path. Run after warehouse.py.

usage: python build.py E2026
"""
import datetime
import glob
import html
import json
import math
import os
import re
import sys
import duckdb

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2026"
ROOT = os.path.dirname(os.path.abspath(__file__))
W = os.path.join(ROOT, "warehouse", SEASON)
OUT = os.path.join(ROOT, "teams", SEASON)
SITE = "https://baranerdogan11.github.io/Euroleague-Player-Lab/"   # public origin, for absolute Open Graph URLs in the share stubs
os.makedirs(OUT, exist_ok=True)
for stale in glob.glob(os.path.join(OUT, "*.json")):
    if os.path.basename(stale) not in ("monitor.json",):      # club files are regenerated; the monitoring snapshot is owned by monitor.py
        os.remove(stale)
label = lambda s: f"{s[1:]}-{str(int(s[1:]) + 1)[2:]}"
STAT_KEYS = ["pts", "fgm2", "fga2", "fgm3", "fga3", "ftm", "fta", "oreb", "dreb", "reb", "ast", "stl", "tov", "blk", "blka", "pf", "fd", "pir", "plusminus"]

con = duckdb.connect()
for t in ["clubs", "players", "roster_stints", "games", "box", "shots"]:
    con.execute(f"create view {t} as select * from read_parquet('{os.path.join(W, t + '.parquet')}')")
xfg_path = os.path.join(W, "shots_xfg.parquet")
HAS_XFG = os.path.exists(xfg_path)
con.execute(f"create view shots_xfg as select * from read_parquet('{xfg_path}')" if HAS_XFG else "create view shots_xfg as select null::int game, null::int seq, null::varchar player, null::double xfg where false")
ctx_path = os.path.join(W, "shot_context.parquet")
con.execute(f"create view shot_context as select * from read_parquet('{ctx_path}')" if os.path.exists(ctx_path) else "create view shot_context as select null::int game, null::int seq, null::int assisted, null::int fouled, null::int blocked, null::int poss_sec where false")
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

# ---- team and opponent totals per game (both sides of every box score), for usage, rebound shares, on/off and pace
TG = {(t["game"], t["club"]): t for t in rows("""select game, club, sum(minutes) tmin, sum(fga2 + fga3) tfga, sum(fta) tfta, sum(tov) ttov, sum(fgm2 + fgm3) tfgm, sum(oreb) toreb, sum(dreb) tdreb,
                                                            sum(pts) tpts, sum(ast) tast from box group by game, club""")}
GAME_CLUBS = {g["game"]: (g["home"], g["away"]) for g in rows("select game, home, away from games")}
def opp_of(game, club):
    h, a = GAME_CLUBS[game]
    return a if club == h else h
def game_poss(game):
    """Possessions in a game, averaged over both sides: FGA - OREB + TOV + 0.44 FTA."""
    h, a = GAME_CLUBS[game]; th, ta = TG.get((game, h)), TG.get((game, a))
    if not th or not ta:
        return None
    return round(((th["tfga"] - th["toreb"] + th["ttov"] + 0.44 * th["tfta"]) + (ta["tfga"] - ta["toreb"] + ta["ttov"] + 0.44 * ta["tfta"])) / 2, 1)


def role_metrics(lines):
    """Usage, assist, turnover and rebound shares, shot mix, and on/off net rating from a player's box lines. None without games."""
    if not lines:
        return None
    acc = {k: 0.0 for k in ("usg_n", "usg_d", "ast", "ast_d", "tov", "tov_d", "oreb", "oreb_d", "dreb", "dreb_d", "fga", "fga3", "fta", "on_pm", "on_min", "off_pm", "off_min", "pm_games")}
    for b in lines:
        t, o = TG.get((b["game"], b["club"])), TG.get((b["game"], opp_of(b["game"], b["club"])))
        if not t or not o or not t["tmin"]:
            continue
        mp, share = b["minutes"], b["minutes"] / (t["tmin"] / 5)
        fga = b["fga2"] + b["fga3"]
        acc["usg_n"] += fga + 0.44 * b["fta"] + b["tov"]; acc["usg_d"] += (t["tfga"] + 0.44 * t["tfta"] + t["ttov"]) * share
        acc["ast"] += b["ast"]; acc["ast_d"] += share * t["tfgm"] - (b["fgm2"] + b["fgm3"])
        acc["tov"] += b["tov"]; acc["tov_d"] += fga + 0.44 * b["fta"] + b["tov"]
        acc["oreb"] += b["oreb"]; acc["oreb_d"] += share * (t["toreb"] + o["tdreb"]); acc["dreb"] += b["dreb"]; acc["dreb_d"] += share * (t["tdreb"] + o["toreb"])
        acc["fga"] += fga; acc["fga3"] += b["fga3"]; acc["fta"] += b["fta"]
        if b["plusminus"] is not None:
            margin = t["tpts"] - o["tpts"]
            acc["on_pm"] += b["plusminus"]; acc["on_min"] += mp; acc["off_pm"] += margin - b["plusminus"]; acc["off_min"] += t["tmin"] / 5 - mp; acc["pm_games"] += 1
    r = lambda n, d, s=100: round(s * n / d, 1) if d > 0 else None
    on = r(acc["on_pm"], acc["on_min"], 40); off = r(acc["off_pm"], acc["off_min"], 40)
    onoff = round(on - off, 1) if on is not None and off is not None else None
    return {"usg": r(acc["usg_n"], acc["usg_d"]), "ast_pct": r(acc["ast"], acc["ast_d"]), "tov_pct": r(acc["tov"], acc["tov_d"]), "oreb_pct": r(acc["oreb"], acc["oreb_d"]), "dreb_pct": r(acc["dreb"], acc["dreb_d"]),
            "reb_pct": r(acc["oreb"] + acc["dreb"], acc["oreb_d"] + acc["dreb_d"]), "fg3_rate": r(acc["fga3"], acc["fga"]), "ft_rate": r(acc["fta"], acc["fga"]),
            "on40": on, "off40": off, "onoff": onoff, "onoff_shrunk": round(onoff * acc["on_min"] / (acc["on_min"] + 1500), 1) if onoff is not None else None, "on_min": round(acc["on_min"]), "pm_games": int(acc["pm_games"])}


POS = {"Guard": "Guard", "Forward": "Forward", "Center": "Center"}
pos_group = lambda p: POS.get((p or "").split()[0].capitalize() if p else "", "Forward")


def zone_of(x, y, pts):
    d = (x * x + y * y) ** 0.5
    if pts == 3:
        return "c3" if y < 141.5 else "a3"
    if d < 150:
        return "rim"
    if abs(x) < 245 and y < 422.5:
        return "paint"
    return "mid"


def defence_adjustments(season):
    """Per defending club and zone, the shrunk residual (made minus context xFG) of the shots taken against it. None while thin."""
    w = os.path.join(ROOT, "warehouse", season)
    if not all(os.path.exists(os.path.join(w, t + ".parquet")) for t in ("shots", "shots_xfg", "games")):
        return None
    q = con.execute(f"""select s.club, g.home, g.away, s.x, s.y, s.pts, s.made::int, x.xfg_ctx from read_parquet('{w}/shots.parquet') s
                        join read_parquet('{w}/shots_xfg.parquet') x using (game, seq) join read_parquet('{w}/games.parquet') g using (game) where x.xfg_ctx is not null""").fetchall()
    if len(q) < 3000:
        return None
    acc = {}
    for club, home, away, x, y, pts, made, xf in q:
        d = acc.setdefault(away if club == home else home, {}).setdefault(zone_of(x, y, pts), [0, 0.0])
        d[0] += 1; d[1] += made - xf
    return {c: {z: round(v[1] / (v[0] + 200), 4) for z, v in zs.items()} for c, zs in acc.items()}


DEF_ADJ = defence_adjustments(SEASON)

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
        # columns 11 to 14 come from the play-by-play layer: assisted (makes only), and-one, blocked (misses only), seconds into the possession
        sh = rows("""select s.game, s.club, s.x, s.y, s.made, s.pts, s.minute, s.zone, s.fastbreak, s.second_chance, x.xfg_ctx, x.xfg, c.assisted, c.fouled, c.blocked, c.poss_sec
                     from shots s left join shots_xfg x using (game, seq) left join shot_context c using (game, seq) where s.player = ? order by s.game, s.minute, s.seq""", r["player"])
        rnd = lambda v: round(v, 3) if v is not None else None
        shots = [[gidx[s["game"]], s["x"], s["y"], int(s["made"]), s["pts"], s["minute"], s["zone"], int(s["fastbreak"]), int(s["second_chance"]), rnd(s["xfg_ctx"]), rnd(s["xfg"]), s["assisted"], s["fouled"], s["blocked"], s["poss_sec"]] for s in sh if s["game"] in gidx]
        scored = [s for s in shots if s[9] is not None]
        xfg = {"att": len(scored), "xfg": round(sum(s[9] for s in scored) / len(scored), 4) if scored else None,
               "xpts": round(sum(s[9] * s[4] for s in scored), 2), "pts": sum(s[3] * s[4] for s in scored)} if scored else None
        if xfg and DEF_ADJ:                        # schedule-adjusted expectation: the defence faced, by zone
            adj = sum((s["made"] - (s["xfg_ctx"] + DEF_ADJ.get(opp_of(s["game"], s["club"]), {}).get(zone_of(s["x"], s["y"], s["pts"]), 0.0))) * s["pts"] for s in sh if s["game"] in gidx and s["xfg_ctx"] is not None)
            xfg["pae_adj"] = round(adj, 2)
        role = role_metrics(lines)
        games = [{"code": b["game"], "round": b["round"], "date": str(b["date"]), "home": b["home"], "away": b["away"], "hs": b["home_score"], "as": b["away_score"], "phase": b["phase"], "own": b["club"],
                  "poss": game_poss(b["game"])} for b in lines]
        players.append({"pid": "P" + r["player"], "name": r["name"], "dorsal": r["dorsal"], "position": r["position"], "height": r["height_cm"],
                        "birth": str(r["birth_date"]) if r["birth_date"] else None, "country": r["country"],
                        "photo": f"photos/{r['player']}.webp" if os.path.exists(os.path.join(ROOT, "photos", f"{r['player']}.webp")) else None,
                        "cur": {"tot": tot, "log": log, "shots": shots, "games": games, "xfg": xfg, "profile": profile_of(r["player"], gidx), "note": note_of(r["player"]), "role": role, "pos_group": pos_group(r["position"])}})
    collected[code] = players

# league percentiles among rotation players (3+ games, 10+ minutes a game), per game and per 40 minutes; turnovers inverted so higher is better
COUNTING = ("pts", "reb", "ast", "stl", "blk", "tov", "pir", "plusminus")
def per_game(tot, per40=False):
    gp = tot["gp"] or 1
    fga = tot["fga2"] + tot["fga3"]
    scale = (40 / tot["min"]) if per40 and tot["min"] else (1 / gp)
    return {**{k: tot[k] * scale for k in COUNTING},
            "fg2": tot["fgm2"] / tot["fga2"] if tot["fga2"] >= 15 else None, "fg3": tot["fgm3"] / tot["fga3"] if tot["fga3"] >= 15 else None,
            "ft": tot["ftm"] / tot["fta"] if tot["fta"] >= 10 else None, "ts": tot["pts"] / (2 * (fga + 0.44 * tot["fta"])) if fga else None}
eligible = lambda tot: tot["gp"] >= 3 and tot["min"] / tot["gp"] >= 10
pools = {False: [], True: []}
ROLE_KEYS = ("usg", "ast_pct", "tov_pct", "reb_pct", "fg3_rate", "ft_rate", "onoff_shrunk")
def full_rates(cur, per40=False):
    d = per_game(cur["tot"], per40)
    d.update({k: (cur["role"] or {}).get(k) for k in ROLE_KEYS})
    return d
pos_pools = {}
for ps in collected.values():
    for p in ps:
        if eligible(p["cur"]["tot"]):
            pools[False].append(full_rates(p["cur"])); pools[True].append(full_rates(p["cur"], True))
            pos_pools.setdefault(p["cur"]["pos_group"], []).append(full_rates(p["cur"]))
league_n = len(pools[False])
INVERT = {"tov", "tov_pct"}
def pct_against(pool, me):
    out = {}
    for k, v in me.items():
        if v is None:
            out[k] = None; continue
        vals = [r[k] for r in pool if r.get(k) is not None]
        out[k] = round(100 * sum(1 for x in vals if (x > v if k in INVERT else x < v)) / len(vals)) if vals else None
    return out
def percentiles(tot, per40=False):
    if league_n < 20 or not eligible(tot):
        return None
    return pct_against(pools[per40], per_game(tot, per40))


def league_refs(season):
    """League FG% and points per attempt by zone, and the shooting splits, from a season's warehouse. None while the season is thin."""
    w = os.path.join(ROOT, "warehouse", season)
    if not all(os.path.exists(os.path.join(w, t + ".parquet")) for t in ("shots", "box")):
        return None
    sh = con.execute(f"select x, y, pts, made::int from read_parquet('{os.path.join(w, 'shots.parquet')}')").fetchall()
    if len(sh) < 1000:
        return None
    acc = {k: [0, 0, 0] for k in ("rim", "paint", "mid", "c3", "a3")}
    for x, y, pts, made in sh:
        z = acc[zone_of(x, y, pts)]; z[0] += 1; z[1] += made; z[2] += made * pts
    acc["three"] = [acc["c3"][i] + acc["a3"][i] for i in range(3)]
    zones = {k: {"att": a, "fg": round(m / a, 4), "ppa": round(p / a, 3)} for k, (a, m, p) in acc.items()}
    # shot mix and finishing by position group, from the same season's roster positions
    by_pos = None
    stint_path = os.path.join(w, "roster_stints.parquet")
    if os.path.exists(stint_path):
        posmap = {p: pos_group(pos) for p, pos in con.execute(f"select player, position from read_parquet('{stint_path}') order by active, start_date").fetchall()}
        pacc = {}
        for x, y, pts, made, player in con.execute(f"select x, y, pts, made::int, player from read_parquet('{os.path.join(w, 'shots.parquet')}')").fetchall():
            z = pacc.setdefault(posmap.get(player, "Forward"), {k: [0, 0] for k in ("rim", "paint", "mid", "c3", "a3")})[zone_of(x, y, pts)]
            z[0] += 1; z[1] += made
        by_pos = {g: {"att": sum(v[0] for v in zs.values()), "zones": {k: {"share": round(v[0] / sum(q[0] for q in zs.values()), 4), "fg": round(v[1] / v[0], 4) if v[0] else None} for k, v in zs.items()}} for g, zs in pacc.items()}
    fgm2, fga2, fgm3, fga3, ftm, fta, pts = con.execute(f"select sum(fgm2), sum(fga2), sum(fgm3), sum(fga3), sum(ftm), sum(fta), sum(pts) from read_parquet('{os.path.join(w, 'box.parquet')}')").fetchone()
    splits = {"fg2": round(fgm2 / fga2, 4), "fg3": round(fgm3 / fga3, 4), "fg": round((fgm2 + fgm3) / (fga2 + fga3), 4), "ft": round(ftm / fta, 4), "ts": round(pts / (2 * (fga2 + fga3 + 0.44 * fta)), 4)}
    return {"season": season, "shots": len(sh), "zones": zones, "splits": splits, "by_pos": by_pos}


league = league_refs(SEASON) or (league_refs(PRIORS["reference_season"]) if PRIORS else None)
for code, players in collected.items():
    for p in players:
        tot = p["cur"]["tot"]
        p["cur"]["pct"] = percentiles(tot)
        p["cur"]["pct40"] = percentiles(tot, True)
        pool = pos_pools.get(p["cur"]["pos_group"], [])
        p["cur"]["pct_pos"] = pct_against(pool if len(pool) >= 20 else pools[False], full_rates(p["cur"])) if league_n >= 20 and eligible(tot) else None
        p["cur"]["pos_n"] = len(pool) if len(pool) >= 20 else league_n
        p["cur"]["per40"] = {k: round(tot[k] * 40 / tot["min"], 1) for k in COUNTING} if tot["min"] else None
    played = con.execute("select count(*) from games where played and ? in (home, away)", [code]).fetchone()[0]
    upcoming = rows("select game as code, round, cast(date as varchar) as date, home, away, phase from games where not played and ? in (home, away) order by date limit 10", code)
    json.dump({"code": code, "season": SEASON, "label": label(SEASON), "games_played": played, "upcoming": upcoming, "players": players, "real_code": code},
              open(os.path.join(OUT, f"{code}.json"), "w"), separators=(",", ":"), ensure_ascii=False)
    summary.append((code, len(players), played, sum(len(p["cur"]["shots"]) for p in players)))
# share stubs: the app is one hash-routed page, which link previews cannot read, so every player gets a static p/<pid>.html carrying his
# Open Graph card (name, club, photo) that forwards straight to his page. "Copy link" on the page hands out these URLs.
def display_name(raw):
    sur, _, first = (raw or "").partition(",")
    fix = lambda t: re.sub(r"(^|[\s\-'.])(\S)", lambda m: m.group(1) + m.group(2).upper(), t.strip().lower())
    return f"{fix(first)} {fix(sur)}".strip()
STUB = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{name} · {club} · Euroleague Player Lab</title>'
        '<meta name="description" content="{desc}"><meta property="og:type" content="profile"><meta property="og:site_name" content="Euroleague Player Lab"><meta property="og:title" content="{name} · {club}">'
        '<meta property="og:description" content="{desc}"><meta property="og:image" content="{image}"><meta property="og:url" content="{url}"><meta name="twitter:card" content="summary">'
        '<link rel="canonical" href="{url}"><meta http-equiv="refresh" content="0;url={rel}"><script>location.replace({rel_js})</script>'
        '<style>body{{margin:0;background:#060708;color:#c6cbd4;font:14px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh}}a{{color:#f26f21}}</style></head>'
        '<body><p>Opening <a href="{rel}">{name}</a> in Euroleague Player Lab…</p></body></html>')
stub_dir = os.path.join(ROOT, "p")
os.makedirs(stub_dir, exist_ok=True)
keep = set()
for code, players in collected.items():
    club = next(c["name"] for c in clubs if c["club"] == code)
    for p in players:
        name = display_name(p["name"]); tot = p["cur"]["tot"]
        line = f"{tot['gp']} games · {tot['pts'] / tot['gp']:.1f} pts · {tot['reb'] / tot['gp']:.1f} reb · {tot['ast'] / tot['gp']:.1f} ast a game" if tot["gp"] else "shot chart, shooting profile and season stats"
        desc = f"{'#' + str(p['dorsal']) + ' · ' if p['dorsal'] else ''}{p['position'] or p['cur']['pos_group']} · {club} · {label(SEASON)} · {line}"
        rel = f"../#{code}/{p['pid']}"
        page = STUB.format(name=html.escape(name), club=html.escape(club), desc=html.escape(desc), image=SITE + (p["photo"] or next((c["logo"] for c in clubs if c["club"] == code), "") or ""),
                           url=f"{SITE}#{code}/{p['pid']}", rel=rel, rel_js=json.dumps(rel))
        fn = f"{p['pid']}.html"; keep.add(fn)
        path = os.path.join(stub_dir, fn)
        if not os.path.exists(path) or open(path, encoding="utf-8").read() != page:
            open(path, "w", encoding="utf-8").write(page)
for fn in os.listdir(stub_dir):
    if fn.endswith(".html") and fn not in keep:
        os.remove(os.path.join(stub_dir, fn))
print(f"share stubs: {len(keep)} under p/")

# position medians for the compare table (same labels as the page)
def compare_metrics(cur):
    tot, role, pr = cur["tot"], cur["role"] or {}, cur["profile"]
    per40 = lambda k: tot[k] * 40 / tot["min"] if tot["min"] else None
    zs = {}
    for s in cur["shots"]:
        k = zone_of(s[1], s[2], s[4]); z = zs.setdefault(k, [0, 0]); z[0] += 1; z[1] += s[3]
    natt = sum(v[0] for v in zs.values()); rim = zs.get("rim", [0, 0]); three = zs.get("c3", [0, 0])[0] + zs.get("a3", [0, 0])[0]
    fga = tot["fga2"] + tot["fga3"]
    return {"Minutes a game": tot["min"] / tot["gp"] if tot["gp"] else None, "Points per 40": per40("pts"), "Usage": role.get("usg"),
            "True shooting": tot["pts"] / (2 * (fga + 0.44 * tot["fta"])) if fga else None, "3P%": tot["fgm3"] / tot["fga3"] if tot["fga3"] >= 15 else None,
            "Assists per 40": per40("ast"), "Assist rate": role.get("ast_pct"), "Turnover rate": role.get("tov_pct"),
            "Rebounds per 40": per40("reb"), "Rebound rate": role.get("reb_pct"), "Rim FG%": rim[1] / rim[0] if rim[0] >= 10 else None, "Share of shots from three": three / natt if natt else None,
            "Shot quality": pr["quality_shrunk"] if pr else None, "Shooting skill per 100": 100 * pr["skill_shrunk"] if pr else None, "On / off per 40": role.get("onoff_shrunk"), "PIR per 40": per40("pir")}
medians = {}
for grp, ps in pos_pools.items():
    vals = {}
    for code, players in collected.items():
        for p in players:
            if p["cur"]["pos_group"] == grp and eligible(p["cur"]["tot"]):
                for k, v in compare_metrics(p["cur"]).items():
                    if v is not None:
                        vals.setdefault(k, []).append(v)
    medians[grp] = {k: round(sorted(v)[len(v) // 2], 3) for k, v in vals.items() if len(v) >= 10}

# ---- league leaderboards: points, rebounds and assists a game, and three-point percentage.
# Qualification is pro-rated off the player's own club's played games, the way the NBA pro-rates its 70%-of-games
# rule in season, so the size of the qualifying pool stays flat as the season grows instead of tripling. The
# three-point board is gated on attempts alone (volume is near-independent of accuracy) and ranked on the raw
# percentage; the gate starts at the 15 attempts the rest of this file already requires before it will print a 3P%.
LB_TOP = 10
LB_MPG = 10.0                     # the minutes half of the app's own pool rule
LB_GAME_SHARE = 0.7               # share of his club's played games a player must have appeared in
LB_ATT_FLOOR = 15                 # the settled gate, matching the attempts per_game() and compare_metrics() require
LB_ATT_PER_ROUND = 2.0
LB_ATT_EARLY = 5                  # floor of the provisional gate used before anyone can reach the settled one


def leaderboards():
    """Four boards plus the per-player ranks the page pins under them. Built from `collected`, not from SQL, so every
    pid on a board resolves to a player the site actually has a page for."""
    cg = {}
    for (game, club) in TG:
        cg[club] = cg.get(club, 0) + 1
    if not cg:
        return None, {}
    counts = sorted(cg.values())
    rounds = counts[len(counts) // 2]                       # median club, so one moved fixture cannot overstate progress
    min_3pa = max(LB_ATT_FLOOR, int(LB_ATT_PER_ROUND * rounds))
    min_gp = max(1, math.ceil(LB_GAME_SHARE * rounds))
    cands = [(p["pid"], p["cur"]["tot"], code) for code, ps in collected.items() for p in ps if p["cur"]["tot"]["gp"]]
    pg_pool = [(pid, t) for pid, t, code in cands
               if t["gp"] >= max(1, math.ceil(LB_GAME_SHARE * cg.get(code, rounds))) and t["min"] / t["gp"] >= LB_MPG]
    a3_pool = [(pid, t) for pid, t, _ in cands if t["fga3"] >= min_3pa]
    # Early in the season nobody has reached the settled gate yet, so rather than show an empty board, drop to the
    # highest attempt count that still fields a full ten. It lifts itself back to the settled gate within a few rounds.
    provisional = False
    if len(a3_pool) < LB_TOP:
        for t in range(min_3pa - 1, LB_ATT_EARLY - 1, -1):
            pool = [(pid, tt) for pid, tt, _ in cands if tt["fga3"] >= t]
            if len(pool) >= LB_TOP:
                min_3pa, a3_pool, provisional = t, pool, True
                break
        else:
            min_3pa, a3_pool, provisional = LB_ATT_EARLY, [(pid, tt) for pid, tt, _ in cands if tt["fga3"] >= LB_ATT_EARLY], True

    def order(key):
        return sorted(pg_pool, key=lambda x: (-x[1][key] / x[1]["gp"], -x[1]["gp"], x[1]["min"], x[0]))

    ranked = {k: order(k) for k in ("pts", "reb", "ast")}
    ranked["fg3"] = sorted(a3_pool, key=lambda x: (-x[1]["fgm3"] / x[1]["fga3"], -x[1]["fga3"], x[0]))
    rank_of = {k: {pid: i + 1 for i, (pid, _) in enumerate(v)} for k, v in ranked.items()}
    out = {"rounds": rounds, "min_gp": min_gp, "min_3pa": min_3pa, "min_mpg": LB_MPG,
           "att_settled": max(LB_ATT_FLOOR, int(LB_ATT_PER_ROUND * rounds)), "provisional": provisional,
           "n": {"pg": len(pg_pool), "fg3": len(a3_pool)},
           "top_3pa": max((t["fga3"] for _, t, _ in cands), default=0),
           "pts": [[pid, t["pts"], t["gp"]] for pid, t in ranked["pts"][:LB_TOP]],
           "reb": [[pid, t["reb"], t["gp"]] for pid, t in ranked["reb"][:LB_TOP]],
           "ast": [[pid, t["ast"], t["gp"]] for pid, t in ranked["ast"][:LB_TOP]],
           "fg3": [[pid, t["fgm3"], t["fga3"]] for pid, t in ranked["fg3"][:LB_TOP]]}
    return out, rank_of


def club_ratings():
    """Season-to-date pace, offensive and defensive rating per club, from the box totals."""
    out = {}
    for (game, club), t in TG.items():
        o = TG.get((game, opp_of(game, club))); poss = game_poss(game)
        if not o or not poss:
            continue
        r = out.setdefault(club, {"g": 0, "poss": 0.0, "pf": 0, "pa": 0})
        r["g"] += 1; r["poss"] += poss; r["pf"] += t["tpts"]; r["pa"] += o["tpts"]
    return {c: {"g": r["g"], "pace": round(r["poss"] / r["g"], 1), "ortg": round(100 * r["pf"] / r["poss"], 1), "drtg": round(100 * r["pa"] / r["poss"], 1)} for c, r in out.items() if r["poss"]}


LEADERS, LB_RANK = leaderboards()
if LEADERS is None:
    LEADERS, LB_RANK = None, {k: {} for k in ("pts", "reb", "ast", "fg3")}

status_path = os.path.join(W, "status.json")
status = json.load(open(status_path)) if os.path.exists(status_path) else None
if status:
    json.dump(status, open(os.path.join(OUT, "status.json"), "w"), indent=1)
card_path = os.path.join(ROOT, "model", "model_card.json")
card = json.load(open(card_path)) if os.path.exists(card_path) else None
meta = {"season": SEASON, "label": label(SEASON), "model": {"version": card["version"], "trained_on": card["trained_on"], "logloss": card["metrics_test"][card["chosen"]]["logloss"],
                                                           "auc": card["metrics_test"][card["chosen"]]["auc"], "n_shots": card["n_shots"]} if card else None, "clubs": [{"code": c["club"], "name": c["name"], "short": c["short"], "country": c["country"], "city": c["city"], "logo": c["logo"], "base": PALETTES.get(c["club"], DEFAULT_PALETTE)[0], "accent": PALETTES.get(c["club"], DEFAULT_PALETTE)[1]} for c in clubs],
        "league_n": league_n, "pool_rule": "3+ games, 10+ minutes a game", "league": league, "def_adjusted": DEF_ADJ is not None,
        "ratings": club_ratings(), "medians": medians, "leaders": LEADERS,
        "roster": [{"pid": p["pid"], "name": p["name"], "club": code, "dorsal": p["dorsal"], "pos": p["cur"]["pos_group"], "ph": 1 if p["photo"] else 0,
                    "lr": [LB_RANK[k].get(p["pid"], 0) for k in ("pts", "reb", "ast", "fg3")]} for code, ps in collected.items() for p in ps],
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
