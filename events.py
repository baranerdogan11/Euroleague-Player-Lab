"""Play-by-play layer: every event of every played game, and the context of every shot derived from it.

Reads cache/<season>/pbp_<game>.json (the live API's PlayByPlay feed, fetched by fetch_season.py) and writes two
Parquet tables next to the rest of the warehouse:
  events        one row per play-by-play event (game, seq), sequence numbers shared with the shots table
  assists       one row per assist (AS) event: the passer, and the scorer and basket it set up (a made two or three, or a
                made free throw after a foul on the pass), so club and player pages can say who set up whom
  shot_context  one row per shot: assisted (makes only, the same link as the assists table), fouled on the shot, blocked (misses only), seconds since
                the possession started, from the scorer's clock (a coarse shot-clock proxy), and how that possession
                began (period start, opponent make, own defensive or offensive rebound, steal, opponent turnover)

usage: python events.py E2026
"""
import glob
import json
import os
import sys
import duckdb
from parquet_io import add_to_manifest, write_parquet

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2026"
ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache", SEASON)
OUT = os.path.join(ROOT, "warehouse", SEASON)
PERIODS = [("FirstQuarter", 1), ("SecondQuarter", 2), ("ThirdQuarter", 3), ("ForthQuarter", 4), ("ExtraTime", 5)]
FG = {"2FGA", "2FGM", "3FGA", "3FGM"}
SCORES = {"2FGM": 2, "3FGM": 3, "FTM": 1}
norm_pid = lambda s: ((s or "").strip()[1:] if (s or "").strip().startswith("P") else (s or "").strip()) or None


def clock_sec(s):
    """'09:39' -> seconds remaining in the period, None when the feed has no clock."""
    if not s or ":" not in s:
        return None
    m, sec = s.split(":")[:2]
    try:
        return int(m) * 60 + int(sec)
    except ValueError:
        return None


def period_of(per, playtype, minute):
    """The feed files every overtime under ExtraTime; its game minute tells them apart (41-45 the first, 46-50 the second,
    and so on), except that an end-of-period marker carries the next minute (the first overtime ends at minute 46)."""
    if per < 5 or minute is None:
        return per
    return 5 + max(0, (minute - (42 if playtype in ("EP", "EG") else 41)) // 5)


def link_assists(evs):
    """Pair every AS event of one game (events in seq order) with the basket it set up. The scorer logs the assist right
    after the basket, its clock a few seconds on (the clock runs while it is typed), but a late correction can insert it
    minutes of game time away from the basket. So: a scoring event of the passer's club, by someone else, in the same
    period, not already claimed, first the nearest of the four events before the assist with the basket's clock at most
    2 seconds after and 15 seconds before the assist's, then the nearest in the period with the clocks within 5 seconds
    (a missing clock matches either way). Box-score assists include passes that drew a shooting foul, so a made free
    throw can be the basket.
    Returns {AS seq: (scorer, scoring seq, points)}; an assist with no such basket is left out (its passer still counts)."""
    claimed, links = set(), {}
    gap = lambda j, a: None if evs[j]["clock_sec"] is None or a["clock_sec"] is None else evs[j]["clock_sec"] - a["clock_sec"]   # seconds the basket came before the assist
    for i, a in enumerate(evs):
        if a["playtype"] != "AS" or not a["club"]:
            continue
        ok = lambda j, lo, hi: (evs[j]["playtype"] in SCORES and evs[j]["club"] == a["club"] and evs[j]["period"] == a["period"] and evs[j]["player"]
                                and evs[j]["player"] != a["player"] and j not in claimed and (gap(j, a) is None or lo <= gap(j, a) <= hi))
        j = next((j for j in range(i - 1, max(i - 5, -1), -1) if ok(j, -2, 15)), None)
        if j is None:
            j = min((j for j in range(len(evs)) if ok(j, -5, 5)), key=lambda j: abs(j - i), default=None)
        if j is not None:
            claimed.add(j)
            links[a["seq"]] = (evs[j]["player"], evs[j]["seq"], SCORES[evs[j]["playtype"]])
    return links


events = []
for path in sorted(glob.glob(os.path.join(CACHE, "pbp_*.json"))):
    gc = int(os.path.basename(path)[4:-5])
    d = json.load(open(path))
    for key, per in PERIODS:
        for e in d.get(key) or []:
            events.append({"game": gc, "seq": e["NUMBEROFPLAY"], "period": period_of(per, (e.get("PLAYTYPE") or "").strip(), e.get("MINUTE")), "club": (e.get("CODETEAM") or "").strip() or None, "player": norm_pid(e.get("PLAYER_ID")),
                           "playtype": (e.get("PLAYTYPE") or "").strip(), "minute": e.get("MINUTE"), "clock": e.get("MARKERTIME") or None, "clock_sec": clock_sec(e.get("MARKERTIME")),
                           "score_home": e.get("POINTS_A"), "score_away": e.get("POINTS_B"), "info": e.get("PLAYINFO") or None})

# ---- per-shot context: walk each game's events in order
context, assists = [], []
by_game = {}
for e in events:
    by_game.setdefault(e["game"], []).append(e)
for gc, evs in by_game.items():
    evs.sort(key=lambda e: e["seq"])
    clubs = [c for c in {e["club"] for e in evs} if c]
    links = link_assists(evs)
    assisted_seqs = {v[1] for v in links.values()}
    assists += [{"game": gc, "seq": e["seq"], "club": e["club"], "passer": e["player"], "scorer": links.get(e["seq"], (None,))[0], "shot_seq": links.get(e["seq"], (None, None))[1],
                 "pts": links.get(e["seq"], (None, None, None))[2]} for e in evs if e["playtype"] == "AS" and e["club"]]
    start = {c: (1, 600, 'period') for c in clubs}   # possession start per club: (period, clock seconds remaining, how it began)
    for i, e in enumerate(evs):
        pt, club, per, cs = e["playtype"], e["club"], e["period"], e["clock_sec"]
        opp = next((c for c in clubs if c != club), None) if club else None
        if pt == "BP":
            for c in clubs:
                start[c] = (per, 300 if per >= 5 else 600, 'period')
        if pt in FG and club:
            made = pt.endswith("M")
            assisted = int(e["seq"] in assisted_seqs) if made else None
            fouled = int(any(x["playtype"] == "RV" and x["club"] == club and x["player"] == e["player"] for x in evs[i + 1:i + 4] if x["period"] == per))
            blocked = None if made else int(any(x["playtype"] == "FV" and x["club"] == opp for x in evs[i + 1:i + 3]))
            sp, sc, kind = start.get(club, (per, None, None))
            poss = (sc - cs) if (cs is not None and sc is not None and sp == per) else None
            if poss is not None and (poss < 0 or poss > 40):
                poss = None
            context.append({"game": gc, "seq": e["seq"], "assisted": assisted, "fouled": fouled, "blocked": blocked, "poss_sec": poss, "poss_start": kind if (poss is not None and sp == per) else None})
            if made and opp:                      # the opponent starts a possession after a make (and after the last free throw of an and-one, handled by FTM below)
                start[opp] = (per, cs, 'make')
        elif club and cs is not None:
            if pt in ("FTM",) and opp:             # each made free throw restarts the opponent's clock; the last one stands
                start[opp] = (per, cs, 'make')
            elif pt in ("D", "ST", "O"):           # own defensive rebound, steal, or offensive rebound: fresh possession for this club
                start[club] = (per, cs, {'D': 'dreb', 'ST': 'steal', 'O': 'oreb'}[pt])
            elif pt == "TO" and opp:              # turnover: the opponent starts (a steal event that follows relabels it)
                start[opp] = (per, cs, 'tov')

con = duckdb.connect()


def to_parquet(name, rows, schema):
    return write_parquet(con, OUT, name, rows, schema)


os.makedirs(OUT, exist_ok=True)
n_ev = to_parquet("events", events, [("game", "INTEGER"), ("seq", "INTEGER"), ("period", "INTEGER"), ("club", "VARCHAR"), ("player", "VARCHAR"), ("playtype", "VARCHAR"), ("minute", "INTEGER"),
                                     ("clock", "VARCHAR"), ("clock_sec", "INTEGER"), ("score_home", "INTEGER"), ("score_away", "INTEGER"), ("info", "VARCHAR")])
n_ctx = to_parquet("shot_context", context, [("game", "INTEGER"), ("seq", "INTEGER"), ("assisted", "INTEGER"), ("fouled", "INTEGER"), ("blocked", "INTEGER"), ("poss_sec", "INTEGER"), ("poss_start", "VARCHAR")])
n_as = to_parquet("assists", assists, [("game", "INTEGER"), ("seq", "INTEGER"), ("club", "VARCHAR"), ("passer", "VARCHAR"), ("scorer", "VARCHAR"), ("shot_seq", "INTEGER"), ("pts", "INTEGER")])
add_to_manifest(OUT, SEASON, {"events": n_ev, "shot_context": n_ctx, "assists": n_as})
linked = sum(1 for a in assists if a["scorer"])
print(f"{SEASON}: {len(by_game)} games with play-by-play, {n_ev} events, {n_ctx} shots with context, {n_as} assists ({linked} matched to their basket)")
