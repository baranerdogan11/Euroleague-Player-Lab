"""Gold layer: per-club site files and index.html, produced by SQL over the warehouse (warehouse/<season>/).

A club's page lists its active roster stints; each player's games, box lines and shots come from every club
he played for this season, so a mid-season move keeps his full record under his current club.
Photos (photos/*.webp) and crests (logos/*.png, served as 128 px logos/*.webp) are referenced by path. Run after warehouse.py.

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
# public origin for the absolute Open Graph URLs in the share stubs: the custom domain once a CNAME file exists, GitHub Pages until then
_cname = os.path.join(ROOT, "CNAME")
SITE = f"https://{open(_cname).read().strip()}/" if os.path.exists(_cname) and open(_cname).read().strip() else "https://baranerdogan11.github.io/Euroleague-Player-Lab/"
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
priors_path = os.path.join(ROOT, "model", "shooting_priors.json")
PRIORS = json.load(open(priors_path)) if os.path.exists(priors_path) else None
rows = lambda q, *a: [dict(zip([d[0] for d in con.description], r)) for r in con.execute(q, a).fetchall()]


def profile_of(player, gidx):
    pr = PROFILES.get(player)
    if pr is None:
        return None
    curve = [[gidx[c[0]], c[1], c[2], c[3], c[4]] for c in pr.curve if c[0] in gidx]
    g = lambda k: (None if pd.isna(getattr(pr, k, None)) else float(getattr(pr, k))) if hasattr(pr, k) else None
    return {"att": int(pr.att), "quality": pr.quality, "quality_shrunk": pr.quality_shrunk, "quality_pct": pr.quality_pct, "quality_pct_lo": g("quality_pct_lo"), "quality_pct_hi": g("quality_pct_hi"),
            "skill": pr.skill, "skill_shrunk": pr.skill_shrunk, "skill_sd": pr.skill_sd, "skill_pct": pr.skill_pct, "skill_pct_lo": g("skill_pct_lo"), "skill_pct_hi": g("skill_pct_hi"), "pae": pr.pae, "curve": curve}


# Broadcast colourways: base tints panels and the hero wedge, accent carries text, marks and controls on a dark ground.
PALETTES = {"IST": ("#002D74", "#00A7E1"),   # Anadolu Efes: navy and light blue, as on the crest
            "MIL": ("#8E1610", "#F0342B"),   # Olimpia Milano: red and white
            "BES": ("#2A2A2A", "#FFFFFF"),   # Besiktas: black and white
            "RED": ("#A3121A", "#FF3B44"),   # Crvena Zvezda: red and white
            "DUB": ("#1A1714", "#C69C4D"),   # Dubai Basketball: black and gold (white kit with black and gold trim; the crest is white, black and bronze)
            "BAR": ("#023485", "#EDBB00"),   # Barcelona: blaugrana blue with the crest's gold
            "MUN": ("#8F0F25", "#EE3149"),   # Bayern Munich: red and white
            "ULK": ("#0A2F5E", "#FFED00"),   # Fenerbahce: navy and yellow
            "HTA": ("#9E1218", "#FF3B44"),   # Hapoel Tel Aviv: red and white
            "BAS": ("#0A2240", "#E4213C"),   # Baskonia: navy and red
            "ASV": ("#1C1C1C", "#A7ABB3"),   # LDLC ASVEL: black and grey since the 2018 rebrand
            "TEL": ("#1B2F6E", "#FFD500"),   # Maccabi Tel Aviv: navy and yellow
            "OLY": ("#9B0A18", "#F03A4A"),   # Olympiacos: red and white
            "PAN": ("#0B6B3A", "#22D37A"),   # Panathinaikos: green and white
            "PRS": ("#151515", "#E63927"),   # Paris Basketball: black with the brand red
            "PAR": ("#2A2A2A", "#FFFFFF"),   # Partizan: black and white
            "MAD": ("#0B3F8F", "#FEBE10"),   # Real Madrid: the crest's blue and gold
            "PAM": ("#0A3792", "#FF6C0E"),   # Valencia: navy and orange
            "VIR": ("#2A2A2A", "#FFFFFF"),   # Virtus Bologna: black and white
            "ZAL": ("#146734", "#3FD07A")}   # Zalgiris: the official green and white
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


def crest_webp(code):
    """The crest the site serves: a 128 px webp made from the feed's 160 px PNG (a fifth of the bytes), written only when missing or stale."""
    src, dst = os.path.join(ROOT, "logos", f"{code}.png"), os.path.join(ROOT, "logos", f"{code}.webp")
    if not os.path.exists(src):
        return f"logos/{code}.webp" if os.path.exists(dst) else None
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
        from PIL import Image
        Image.open(src).convert("RGBA").resize((128, 128), Image.LANCZOS).save(dst, "WEBP", quality=85, method=6)
    return f"logos/{code}.webp"


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
    c["logo"] = crest_webp(c["club"])
summary = []
collected = {}
# Euroleague career as spells: consecutive seasons at one club fold into "from-to", most recent first; club names are the
# current short name where the club is in the league today, else the name the feed used that season
CAREERS = {}
career_path = os.path.join(W, "careers.parquet")
if os.path.exists(career_path):
    for pl, season, club, club_name in con.execute(f"select player, season, club, club_name from read_parquet('{career_path}') order by player, season").fetchall():
        CAREERS.setdefault(pl, []).append((int(season[1:]), club, club_name))
SHORT = {c["club"]: c["short"] for c in clubs}
SEASON_END = int(SEASON[1:]) + 1
WIKI = {}
wiki_path = os.path.join(W, "careers_wiki.parquet")
if os.path.exists(wiki_path):
    for pl, ord_, team, y0, y1, league, page in con.execute(f"select player, ord, team, from_year, to_year, league, page from read_parquet('{wiki_path}') order by player, ord").fetchall():
        WIKI.setdefault(pl, {"page": page, "spells": []})["spells"].append({"name": team, "from": y0, "to": y1, "league": league})


def el_spells(player):
    """Euroleague seasons folded into club spells, oldest first."""
    spells = []
    for year, club, club_name in CAREERS.get(player, []):
        if spells and spells[-1]["club"] == club and spells[-1]["to"] == year:
            spells[-1]["to"] = year + 1
            spells[-1]["name"] = SHORT.get(club, club_name)          # a club that changed its sponsor name is shown under its latest one
        else:
            spells.append({"club": club, "name": SHORT.get(club, club_name), "from": year, "to": year + 1})
    return spells


def career_of(player, club):
    """Most recent first. Wikipedia's full history when the player has a matched page; otherwise the Euroleague seasons
    alone. Either way the list ends on the current club for this season, named as the app names it."""
    el = el_spells(player)
    current = {"club": club, "name": SHORT.get(club, club), "from": int(SEASON[1:]), "to": SEASON_END, "league": None}
    if el and el[-1]["club"] == club:
        current["from"] = el[-1]["from"]
    w = WIKI.get(player)
    if not w:
        out = [{**s, "league": None} for s in el]
        if not out or out[-1]["club"] != club:
            out.append(current)
        else:
            out[-1] = {**out[-1], "to": max(out[-1]["to"], SEASON_END)}
        return [{"name": s["name"], "from": s["from"], "to": s["to"], "league": s["league"]} for s in out[::-1]]
    spells = []
    for s in w["spells"]:
        spells.append({"name": s["name"], "from": s["from"], "to": s["to"], "league": s["league"]})
    # the open-ended last spell is the current club: name it as the app does and close it on this season
    last = spells[-1] if spells else None
    if last and last["to"] is None:
        last["name"] = current["name"]; last["to"] = SEASON_END
        if last["from"] is None:
            last["from"] = current["from"]
    else:
        spells.append({"name": current["name"], "from": current["from"], "to": SEASON_END, "league": None})
    return spells[::-1]


for c in clubs:
    code = c["club"]
    roster = rows("""select s.player, p.name, s.dorsal, s.position, p.height_cm, p.weight_kg, p.birth_date, p.country
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
        # "expected" figure on the page uses column 9 so the season stats and the profile panel agree
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
        # the same shares for each game on its own, in log order, so the stats band can show a single game
        role_g = [{k: m[k] for k in ("usg", "ast_pct", "tov_pct", "reb_pct")} if (m := role_metrics([b])) else None for b in lines]
        games = [{"code": b["game"], "round": b["round"], "date": str(b["date"]), "home": b["home"], "away": b["away"], "hs": b["home_score"], "as": b["away_score"], "phase": b["phase"], "own": b["club"],
                  "poss": game_poss(b["game"])} for b in lines]
        players.append({"pid": "P" + r["player"], "name": r["name"], "dorsal": r["dorsal"], "position": r["position"], "height": r["height_cm"], "weight": r["weight_kg"], "career": career_of(r["player"], code), "career_src": "wikipedia" if r["player"] in WIKI else "euroleague",
                        "birth": str(r["birth_date"]) if r["birth_date"] else None, "country": r["country"],
                        "photo": f"photos/{r['player']}.webp" if os.path.exists(os.path.join(ROOT, "photos", f"{r['player']}.webp")) else None,
                        "cur": {"tot": tot, "log": log, "shots": shots, "games": games, "xfg": xfg, "profile": profile_of(r["player"], gidx), "role": role, "role_g": role_g, "pos_group": pos_group(r["position"])}})
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
        '<meta property="og:description" content="{desc}"><meta property="og:image" content="{image}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta property="og:url" content="{url}"><meta name="twitter:card" content="summary_large_image">'
        '<link rel="canonical" href="{self}"><script>try{{sessionStorage.setItem("pl-in","1")}}catch(e){{}}location.replace({rel_js})</script>'
        '<style>body{{margin:0;background:#060708;color:#c6cbd4;font:15px/1.5 system-ui,sans-serif}}main{{max-width:720px;margin:0 auto;padding:36px 20px}}h1{{font-size:34px;line-height:1.05;margin:0 0 4px;color:#fff}}h1 span{{color:{accent}}}'
        'p{{margin:8px 0}}a{{color:{accent}}}img{{max-width:100%;height:auto;display:block;margin:18px 0}}dl{{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:14px 0}}dt{{color:#8a919f;text-transform:uppercase;font-size:12px;letter-spacing:.12em}}dd{{margin:0}}'
        'ol{{padding-left:20px}}.go{{display:inline-block;margin-top:14px;padding:12px 20px;background:{accent};color:#0b0d10;font-weight:800;text-decoration:none;text-transform:uppercase;letter-spacing:.12em}}</style></head>'
        '<body><main><p>{club} · Euroleague {season}</p><h1>{first} <span>{sur}</span></h1><p>{desc}</p><img src="../cards/{pid}.jpg" alt="" width="1200" height="630">'
        '<dl>{facts}</dl>{career}<a class="go" href="{rel}">Open in Player Lab</a><p><a href="../">Euroleague Player Lab</a>: shot charts, shooting profiles and season stats for every player, rebuilt after every game.</p></main></body></html>')
# share cards: one 1200x630 JPEG per player for link previews (about 45 KB each; PNG would be five times that), drawn from the roster fields alone (name, number, club, position,
# photo) so it changes only when those do; cards/manifest.json holds each card's input hash and skips the unchanged ones
import hashlib
CARDS = os.path.join(ROOT, "cards"); os.makedirs(CARDS, exist_ok=True)
FONT_DIR = os.path.join(ROOT, "fonts")
card_manifest_path = os.path.join(CARDS, "manifest.json")
card_manifest = json.load(open(card_manifest_path)) if os.path.exists(card_manifest_path) else {}
def hex_rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
def font(name, size):
    from PIL import ImageFont
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)
def fit(draw, text, name, size, max_w, floor=40):
    """The largest size at or under `size` at which `text` fits `max_w`."""
    while size > floor:
        f = font(name, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 4
    return font(name, floor)
def draw_card(p, club, base, accent, out):
    from PIL import Image, ImageDraw
    Wc, Hc = 1200, 630
    im = Image.new("RGB", (Wc, Hc), (14, 16, 19)); d = ImageDraw.Draw(im)
    b, a = hex_rgb(base), hex_rgb(accent)
    lum = 0.2126 * b[0] + 0.7152 * b[1] + 0.0722 * b[2]
    wedge = b if lum > 18 else tuple(min(255, v + 46) for v in b)     # near-black bases lift so the wedge keeps its shape
    d.polygon([(0, 0), (560, 0), (440, Hc), (0, Hc)], fill=wedge)
    for x in range(-40, Wc + 40, 44):                                  # the hazard stripe along the top
        d.polygon([(x, 0), (x + 22, 0), (x + 10, 14), (x - 12, 14)], fill=a)
    d.rectangle([0, 14, Wc, 16], fill=(36, 39, 46))
    first_last = display_name(p["name"]).split(" ", 1)
    first, sur = (first_last[0], first_last[1]) if len(first_last) == 2 else ("", first_last[0])
    # photo on the wedge, number behind it
    if p["dorsal"]:
        fn = font("BarlowCondensed-BlackItalic.ttf", 300)
        d.text((30, Hc - 300), str(p["dorsal"]), font=fn, fill=tuple(min(255, v + 28) for v in wedge))
    if p["photo"] and os.path.exists(os.path.join(ROOT, p["photo"])):
        ph = Image.open(os.path.join(ROOT, p["photo"])).convert("RGBA")
        h = Hc - 40; w = round(ph.width * h / ph.height); ph = ph.resize((w, h), Image.BICUBIC)
        im.paste(ph, (110, Hc - h), ph)
    # name, club, position on the right
    x0 = 600
    d.text((x0, 60), f"EUROLEAGUE {label(SEASON)}", font=font("BarlowCondensed-Bold.ttf", 30), fill=(138, 145, 159))
    y = 110
    if first:
        f1 = fit(d, first.upper(), "BarlowCondensed-BlackItalic.ttf", 96, Wc - x0 - 40); d.text((x0, y), first.upper(), font=f1, fill=(255, 255, 255)); y += 96
    f2 = fit(d, sur.upper(), "BarlowCondensed-BlackItalic.ttf", 132, Wc - x0 - 40, 56); d.text((x0, y), sur.upper(), font=f2, fill=a); y += int(f2.size * 1.05) + 14
    line = " · ".join(x for x in ((f"#{p['dorsal']}" if p["dorsal"] else ""), club, p["position"] or "") if x)
    d.text((x0, y), line.upper(), font=fit(d, line.upper(), "BarlowCondensed-Bold.ttf", 34, Wc - x0 - 40, 24), fill=(198, 203, 212))
    d.text((x0, Hc - 70), "Shot chart · shooting profile · season stats", font=font("Barlow-Regular.ttf", 24), fill=(138, 145, 159))
    d.text((Wc - 40 - d.textlength("elplayerlab.com", font=font("BarlowCondensed-Bold.ttf", 28)), Hc - 46), "elplayerlab.com", font=font("BarlowCondensed-Bold.ttf", 28), fill=a)
    im.save(out, "JPEG", quality=80, optimize=True, progressive=True)
def home_card(out):
    from PIL import Image, ImageDraw
    Wc, Hc = 1200, 630
    im = Image.new("RGB", (Wc, Hc), (6, 7, 8)); d = ImageDraw.Draw(im)
    for x in range(-40, Wc + 40, 44):
        d.polygon([(x, 0), (x + 22, 0), (x + 10, 14), (x - 12, 14)], fill=(242, 111, 33))
    # a faint half court on the right
    g = (34, 38, 46); cx, by = 1000, Hc + 4                              # basket end at the bottom edge
    d.rectangle([cx - 560, 30, cx + 560, by], outline=g, width=4)         # the half court, running off the right edge
    d.rectangle([cx - 100, by - 300, cx + 100, by], outline=g, width=4)   # the key
    d.ellipse([cx - 72, by - 372, cx + 72, by - 228], outline=g, width=4) # free-throw circle
    d.arc([cx - 340, by - 340, cx + 340, by + 340], 180, 360, fill=g, width=4)   # three-point arc
    d.arc([cx - 60, by - 110, cx + 60, by + 10], 180, 360, fill=g, width=4)      # restricted area
    d.text((80, 150), "PLAYER", font=font("BarlowCondensed-BlackItalic.ttf", 180), fill=(255, 255, 255))
    d.text((80, 300), "LAB", font=font("BarlowCondensed-BlackItalic.ttf", 180), fill=(242, 111, 33))
    d.text((84, 90), f"EUROLEAGUE {label(SEASON)}", font=font("BarlowCondensed-Bold.ttf", 34), fill=(138, 145, 159))
    d.text((84, 500), "Every shot, every player, every club.", font=font("Barlow-Regular.ttf", 32), fill=(198, 203, 212))
    d.text((84, 545), "Shot charts, shooting profiles and season stats, rebuilt within minutes of every final.", font=font("Barlow-Regular.ttf", 24), fill=(138, 145, 159))
    im.save(out, "PNG", optimize=True)
os.makedirs(os.path.join(ROOT, "og"), exist_ok=True)
if not os.path.exists(os.path.join(ROOT, "og", "home.png")):
    home_card(os.path.join(ROOT, "og", "home.png"))
stub_dir = os.path.join(ROOT, "p")
os.makedirs(stub_dir, exist_ok=True)
keep = set()
cards_drawn = 0
for code, players in collected.items():
    club = next(c["name"] for c in clubs if c["club"] == code)
    for p in players:
        name = display_name(p["name"]); tot = p["cur"]["tot"]
        line = f"{tot['gp']} games · {tot['pts'] / tot['gp']:.1f} pts · {tot['reb'] / tot['gp']:.1f} reb · {tot['ast'] / tot['gp']:.1f} ast a game" if tot["gp"] else "shot chart, shooting profile and season stats"
        desc = f"{'#' + str(p['dorsal']) + ' · ' if p['dorsal'] else ''}{p['position'] or p['cur']['pos_group']} · {club} · {label(SEASON)} · {line}"
        rel = f"../#{code}/{p['pid']}"
        photo_path = os.path.join(ROOT, p["photo"]) if p["photo"] else None
        digest = hashlib.sha1(json.dumps([p["name"], p["dorsal"], p["position"], club, code, p["photo"], hashlib.sha1(open(photo_path, "rb").read()).hexdigest() if photo_path and os.path.exists(photo_path) else None, 2]).encode()).hexdigest()[:16]
        card = os.path.join(CARDS, f"{p['pid']}.jpg")
        if card_manifest.get(p["pid"]) != digest or not os.path.exists(card):
            base, accent = PALETTES.get(code, DEFAULT_PALETTE); draw_card(p, club, base, accent, card); card_manifest[p["pid"]] = digest; cards_drawn += 1
        parts = name.split(" ", 1); first, sur = (parts[0], parts[1]) if len(parts) == 2 else ("", parts[0])
        facts = "".join(f"<dt>{k}</dt><dd>{html.escape(str(v))}</dd>" for k, v in (("Number", p["dorsal"]), ("Position", p["position"]), ("Height", f"{p['height']} cm" if p["height"] else None), ("Weight", f"{p['weight']} kg" if p["weight"] else None), ("Born", p["birth"]), ("Country", p["country"])) if v)
        spell = lambda s: f"{s['name']}{' (' + s['league'] + ')' if s.get('league') else ''} {s['from'] or ''}{('-' + str(s['to'])) if s.get('to') and s['to'] != s['from'] else ''}".strip()
        career_html = f"<h2>Career</h2><ol>{''.join(f'<li>{html.escape(spell(s))}</li>' for s in p['career'])}</ol>" if p.get("career") else ""
        page = STUB.format(name=html.escape(name), first=html.escape(first), sur=html.escape(sur), club=html.escape(club), desc=html.escape(desc), image=f"{SITE}cards/{p['pid']}.jpg", pid=p["pid"],
                           url=f"{SITE}#{code}/{p['pid']}", self=f"{SITE}p/{p['pid']}.html", rel=rel, rel_js=json.dumps(rel), accent=PALETTES.get(code, DEFAULT_PALETTE)[1], season=label(SEASON), facts=facts, career=career_html)
        fn = f"{p['pid']}.html"; keep.add(fn)
        path = os.path.join(stub_dir, fn)
        if not os.path.exists(path) or open(path, encoding="utf-8").read() != page:
            open(path, "w", encoding="utf-8").write(page)
for fn in os.listdir(stub_dir):
    if fn.endswith(".html") and fn not in keep:
        os.remove(os.path.join(stub_dir, fn))
for pid in [k for k in card_manifest if f"{k}.html" not in keep]:      # a player who left the league loses his card
    card_manifest.pop(pid, None)
    if os.path.exists(os.path.join(CARDS, f"{pid}.jpg")): os.remove(os.path.join(CARDS, f"{pid}.jpg"))
json.dump(card_manifest, open(card_manifest_path, "w"), indent=0, sort_keys=True)
print(f"share stubs: {len(keep)} under p/, cards drawn: {cards_drawn}")
# search engines: every player page listed, the code and data folders kept out, and a 404 in house style with the club grid and the search
status_path = os.path.join(W, "status.json")
_st = json.load(open(status_path)) if os.path.exists(status_path) else {}
lastmod = (_st.get("checked_at") or datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))[:10]
urls = [SITE, SITE + "monitor.html"] + [f"{SITE}p/{fn[:-5]}.html" for fn in sorted(keep)]
open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8").write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    + "".join(f"  <url><loc>{u}</loc><lastmod>{lastmod}</lastmod></url>\n" for u in urls) + "</urlset>\n")
open(os.path.join(ROOT, "robots.txt"), "w", encoding="utf-8").write("User-agent: *\nAllow: /\nDisallow: /build.py\nDisallow: /README.md\nDisallow: /model/\nDisallow: /tests/\nDisallow: /warehouse/\nDisallow: /cache/\nDisallow: /service/\nDisallow: /teams/\nDisallow: /data/\n"
    + f"Sitemap: {SITE}sitemap.xml\n")
club_grid = "".join(f'<a href="/#{c["club"]}"><img src="/{c["logo"]}" alt="" width="34" height="34" loading="lazy">{html.escape(c["short"] or c["club"])}</a>' for c in clubs if c["logo"])
open(os.path.join(ROOT, "404.html"), "w", encoding="utf-8").write(f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Page not found · Euroleague Player Lab</title><meta name="robots" content="noindex"><link rel="icon" href="/icons/icon-192.png">
<style>@font-face{{font-family:'Barlow Condensed';font-style:italic;font-weight:900;font-display:swap;src:url(/fonts/cond-900i.woff2) format('woff2')}}@font-face{{font-family:'Barlow Condensed';font-weight:700;font-display:swap;src:url(/fonts/cond-700.woff2) format('woff2')}}
body{{margin:0;background:#060708;color:#c6cbd4;font:15px/1.5 Barlow,system-ui,sans-serif}}.bar{{height:6px;background:repeating-linear-gradient(-60deg,#1f2b47 0 18px,#f26f21 18px 22px,#1f2b47 22px 40px)}}main{{max-width:1180px;margin:0 auto;padding:48px 20px 64px}}
h1{{font-family:'Barlow Condensed',Impact,sans-serif;font-style:italic;font-weight:900;font-size:clamp(56px,10vw,120px);line-height:.85;margin:0;text-transform:uppercase;color:#fff}}h1 span{{color:#f26f21;display:block}}p{{max-width:56ch;font-size:17px}}
.q{{margin:24px 0 8px;max-width:440px;position:relative}}.q input{{width:100%;box-sizing:border-box;background:transparent;border:0;border-bottom:2px solid #343841;color:#fff;font:700 19px 'Barlow Condensed',sans-serif;letter-spacing:.06em;text-transform:uppercase;padding:8px 0 6px;outline:0}}.q input:focus{{border-bottom-color:#f26f21}}
.q ul{{list-style:none;margin:0;padding:6px 0;background:#0e1013;border:1px solid #343841;border-top:3px solid #f26f21;position:absolute;left:0;right:0;z-index:2}}.q li a{{display:flex;gap:12px;padding:9px 14px;color:#c6cbd4;text-decoration:none;font:700 16px 'Barlow Condensed',sans-serif;text-transform:uppercase}}.q li a:hover{{background:#191c22;color:#fff}}.q li small{{margin-left:auto;color:#8a919f;font-size:12px;letter-spacing:.08em}}
h2{{font-family:'Barlow Condensed',sans-serif;font-weight:700;font-size:14px;letter-spacing:.2em;text-transform:uppercase;color:#8a919f;margin:36px 0 12px}}.clubs{{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:1px;background:#24272e;border:1px solid #24272e}}
.clubs a{{display:flex;flex-direction:column;align-items:center;gap:8px;padding:14px 6px 11px;background:#0e1013;color:#c6cbd4;text-decoration:none;font:700 11px 'Barlow Condensed',sans-serif;letter-spacing:.1em;text-transform:uppercase;text-align:center}}.clubs a:hover{{background:#191c22;color:#fff}}.clubs img{{filter:drop-shadow(0 0 2.5px rgba(255,255,255,.45))}}
.home{{display:inline-block;margin-top:28px;padding:14px 26px;background:#f26f21;color:#0b0d10;font:800 16px 'Barlow Condensed',sans-serif;letter-spacing:.16em;text-transform:uppercase;text-decoration:none;clip-path:polygon(10px 0,100% 0,calc(100% - 10px) 100%,0 100%)}}</style></head>
<body><div class="bar"></div><main><h1>Not<span>found</span></h1><p>That address has no page. Find a player below, pick a club, or start from the opening page.</p>
<div class="q"><input type="search" id="q" placeholder="Find a player" aria-label="Find a player" autocomplete="off"><ul id="hits" hidden></ul></div>
<h2>Clubs</h2><div class="clubs">{club_grid}</div><a class="home" href="/">Opening page</a></main>
<script>
const fold = s => (s || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase();
const cap = s => s.toLowerCase().replace(/(^|[\\s\\-'.])(\\S)/g, (m, p, c) => p + c.toUpperCase());
let roster = null; const q = document.getElementById('q'), hits = document.getElementById('hits');
q.addEventListener('input', async () => {{
  if (!roster) {{ try {{ roster = await (await fetch('/teams/{SEASON}/roster.json')).json(); }} catch (e) {{ roster = []; }} }}
  const t = fold(q.value).trim().split(/\\s+/).filter(Boolean); if (!t.length) {{ hits.hidden = true; return; }}
  const rows = roster.filter(r => {{ const w = fold(r.name + ' ' + r.club); return t.every(x => w.includes(x)); }}).slice(0, 8);
  hits.innerHTML = rows.map(r => {{ const [sur, first] = r.name.split(',').map(s => s.trim()); return `<li><a href="/p/${{r.pid}}.html">${{cap(first || '')}} ${{cap(sur)}}<small>${{r.club}}</small></a></li>`; }}).join('') || '<li><a>No player matches</a></li>';
  hits.hidden = false;
}});
</script></body></html>''')
print("sitemap.xml, robots.txt, 404.html written")
# build feed: one item per build that changed the game or shot count, newest first, as JSON Feed and RSS
hist_path = os.path.join(W, "run_history.jsonl")
runs = [json.loads(l) for l in open(hist_path, encoding="utf-8") if l.strip()] if os.path.exists(hist_path) else []
items, prev = [], None
for r in runs:
    if not r.get("ok"):
        continue
    key = (r.get("games"), r.get("shots"))
    if key != prev:
        items.append(r)
    prev = key
items = items[-40:][::-1]
def item_text(r):
    return f"{r.get('games', 0)} games in, {r.get('shots', 0):,} shots charted, {r.get('players', 0)} players with stats."
feed = {"version": "https://jsonfeed.org/version/1.1", "title": "Euroleague Player Lab: updates", "home_page_url": SITE, "feed_url": SITE + "feed.json",
        "description": "One entry per rebuild that added games or shots.",
        "items": [{"id": r.get("run_id") or r["at"], "url": SITE, "title": f"Update {r['at'][:16].replace('T', ' ')} UTC: {r.get('games', 0)} games, {r.get('shots', 0):,} shots", "content_text": item_text(r), "date_published": r["at"]} for r in items]}
json.dump(feed, open(os.path.join(ROOT, "feed.json"), "w"), indent=1)
def rfc822(iso):
    return datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").strftime("%a, %d %b %Y %H:%M:%S +0000")
open(os.path.join(ROOT, "feed.xml"), "w", encoding="utf-8").write('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
    f"<title>Euroleague Player Lab: updates</title><link>{SITE}</link><description>One entry per rebuild that added games or shots.</description>"
    + "".join(f"<item><title>{html.escape(i['title'])}</title><link>{SITE}</link><guid isPermaLink=\"false\">{html.escape(i['id'])}</guid><pubDate>{rfc822(i['date_published'])}</pubDate><description>{html.escape(i['content_text'])}</description></item>" for i in feed["items"])
    + "</channel></rss>\n")
# fixture calendars: one .ics per club with every game of the season, results filled in as they land
CAL = os.path.join(ROOT, "cal"); os.makedirs(CAL, exist_ok=True)
club_name = {c["club"]: c["name"] for c in clubs}
ics_esc = lambda s: str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
for c in clubs:
    code = c["club"]
    gs = rows("select game, round, phase, date_utc, home, away, home_score, away_score, played from games where ? in (home, away) order by date_utc", code)
    ev = []
    for g in gs:
        if not g["date_utc"]:
            continue
        start = g["date_utc"]; end = start + datetime.timedelta(hours=2)
        title = f"R{g['round']} {club_name.get(g['home'], g['home'])} vs {club_name.get(g['away'], g['away'])}"
        desc = f"Final {g['home_score']}-{g['away_score']}" if g["played"] else "Euroleague fixture"
        ev.append("BEGIN:VEVENT\r\n" + f"UID:el{SEASON}-g{g['game']}@elplayerlab.com\r\nDTSTAMP:{stamp}\r\nDTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}\r\nDTEND:{end.strftime('%Y%m%dT%H%M%SZ')}\r\n"
                  f"SUMMARY:{ics_esc(title)}\r\nDESCRIPTION:{ics_esc(desc)}\r\nURL:{SITE}#{code}\r\nEND:VEVENT\r\n")
    body = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Euroleague Player Lab//EN\r\nCALSCALE:GREGORIAN\r\nMETHOD:PUBLISH\r\n"
            f"X-WR-CALNAME:{ics_esc(c['name'])} · Euroleague {label(SEASON)}\r\nX-WR-TIMEZONE:UTC\r\n" + "".join(ev) + "END:VCALENDAR\r\n")
    path = os.path.join(CAL, f"{code}.ics")
    old = open(path, encoding="utf-8", newline="").read() if os.path.exists(path) else ""   # newline="" keeps the CRLF so the compare below is exact
    if re.sub(r"DTSTAMP:\S+", "", old) != re.sub(r"DTSTAMP:\S+", "", body):   # rewrite only when a fixture or result changed, not on every build
        open(path, "w", encoding="utf-8", newline="").write(body)
print(f"feed.json, feed.xml ({len(items)} items), cal/*.ics ({len(clubs)} clubs) written")

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
# app icons drawn from the house mark (a dark square, the orange ball, court lines), written once
def draw_icons():
    from PIL import Image, ImageDraw
    os.makedirs(os.path.join(ROOT, "icons"), exist_ok=True)
    def mark(size, pad):
        im = Image.new("RGBA", (size, size), (6, 7, 8, 255)); d = ImageDraw.Draw(im)
        r = size * (22 / 64) * (1 - pad); cx = cy = size / 2; w = max(2, round(size * 3 / 64))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(242, 111, 33, 255))
        d.line([cx - r, cy, cx + r, cy], fill=(6, 7, 8, 255), width=w); d.line([cx, cy - r, cx, cy + r], fill=(6, 7, 8, 255), width=w)
        a = r * 0.68
        d.arc([cx - r - a, cy - a * 1.05, cx - r + a, cy + a * 1.05], 300, 60, fill=(6, 7, 8, 255), width=w)
        d.arc([cx + r - a, cy - a * 1.05, cx + r + a, cy + a * 1.05], 120, 240, fill=(6, 7, 8, 255), width=w)
        return im
    for name, size, pad in (("icon-192.png", 192, 0.0), ("icon-512.png", 512, 0.0), ("icon-maskable-512.png", 512, 0.22), ("apple-touch-icon.png", 180, 0.06)):
        path = os.path.join(ROOT, "icons", name)
        if not os.path.exists(path):
            mark(size, pad).save(path, "PNG", optimize=True)
draw_icons()
# the service worker carries the build stamp so every build replaces the cached page and JSON
sw = open(os.path.join(ROOT, "sw.js"), encoding="utf-8").read()
if "/*BUILT*/" not in sw:
    sw = re.sub(r"const V = 'pl-[^']*';", "const V = 'pl-/*BUILT*/';", sw, count=1)
open(os.path.join(ROOT, "sw.js"), "w", encoding="utf-8").write(sw.replace("/*BUILT*/", meta["built"].replace(" ", "_").replace(":", "")))
# the roster (search index, compare peers, leaderboard names) is 40 KB the cover never needs, so the page fetches it after first paint
json.dump(meta["roster"], open(os.path.join(OUT, "roster.json"), "w"), separators=(",", ":"), ensure_ascii=False)
inline = {k: v for k, v in meta.items() if k != "roster"}; inline["n_players"] = len(meta["roster"])
tpl = open(os.path.join(ROOT, "template.html"), encoding="utf-8").read()
open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(tpl.replace("/*META*/", json.dumps(inline, ensure_ascii=False)).replace("/*OG*/", SITE + "og/home.png"))
for s in summary:
    print("%-4s players %2d  games %2d  shots %4d" % s)
print("index.html + teams/%s/*.json written from warehouse" % SEASON)
