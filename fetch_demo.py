"""Build a demo club from a past season so the app has populated data before the current season's games.

usage: python fetch_demo.py E2025 ULK "HALL, DEVON"
Writes data/<season_out>/DEMO.json (same shape as fetch_season output, one player) and the player's photo.
"""
import json
import os
import sys
import time
import requests
from PIL import Image

SRC_SEASON, CLUB, PLAYER = (sys.argv[1], sys.argv[2], sys.argv[3]) if len(sys.argv) > 3 else ("E2025", "ULK", "HALL, DEVON")
OUT_SEASON = sys.argv[4] if len(sys.argv) > 4 else "E2026"
ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache", f"{SRC_SEASON}_demo")
os.makedirs(CACHE, exist_ok=True)
os.makedirs(os.path.join(ROOT, "photos"), exist_ok=True)
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
FEEDS = "https://feeds.incrowdsports.com/provider/euroleague-feeds/v2/competitions/E/seasons"
LIVE = "https://live.euroleague.net/api"


def get(url, params=None, as_json=True):
    for attempt in range(6):
        r = requests.get(url, headers=H, params=params, timeout=60)
        if r.ok:
            time.sleep(0.35)
            return r.json() if as_json else r.content
        time.sleep(6 * (attempt + 1) if r.status_code == 429 else 2)
    raise RuntimeError(f"{r.status_code} {url}")


def cached(name, fetch):
    path = os.path.join(CACHE, name)
    if os.path.exists(path):
        return json.load(open(path))
    data = fetch()
    json.dump(data, open(path, "w"))
    return data


roster = cached(f"roster_{CLUB}.json", lambda: (lambda j: j["data"] if isinstance(j, dict) else j)(get(f"{FEEDS}/{SRC_SEASON}/clubs/{CLUB}/people", {"personType": "J"})))
entry = next(p for p in roster if p.get("type") == "J" and p["person"]["name"].upper() == PLAYER.upper())
pc = entry["person"]["code"]
url = (entry.get("images") or {}).get("headshot") or (entry.get("images") or {}).get("action")
photo = None
if url:
    raw = os.path.join(CACHE, f"photo_{pc}.bin")
    if not os.path.exists(raw):
        open(raw, "wb").write(get(url, as_json=False))
    im = Image.open(raw).convert("RGBA")
    im = im.resize((int(im.width * 480 / im.height), 480), Image.LANCZOS)
    photo = f"photos/{pc}.webp"
    im.save(os.path.join(ROOT, photo), "WEBP", quality=80, method=6)

games = cached("games.json", lambda: get(f"{FEEDS}/{SRC_SEASON}/games", {"limit": 500})["data"])
played = sorted([g for g in games if CLUB in (g["home"]["code"], g["away"]["code"]) and (g["home"]["score"] or 0) + (g["away"]["score"] or 0) > 0], key=lambda g: g["date"])
shots, box = [], []
for g in played:
    gc = g["code"]
    rows = cached(f"points_{gc}.json", lambda: get(f"{LIVE}/Points", {"gamecode": gc, "seasoncode": SRC_SEASON})["Rows"])
    for r in rows:
        act = r["ID_ACTION"].strip()
        if r["ID_PLAYER"].strip() != "P" + pc or act not in ("2FGM", "2FGA", "3FGM", "3FGA"):
            continue
        shots.append({"game": gc, "pid": "P" + pc, "x": r["COORD_X"], "y": r["COORD_Y"], "made": act.endswith("M"), "pts": 3 if act.startswith("3") else 2,
                      "zone": r["ZONE"].strip(), "q": r["MINUTE"], "clock": r["CONSOLE"], "fastbreak": r["FASTBREAK"] == "1", "second_chance": r["SECOND_CHANCE"] == "1"})
    j = cached(f"box_{gc}.json", lambda: get(f"{LIVE}/Boxscore", {"gamecode": gc, "seasoncode": SRC_SEASON}))
    for side in j.get("Stats", []):
        for p in side.get("PlayersStats", []):
            if p["Player_ID"].strip() != "P" + pc:
                continue
            box.append({"game": gc, "pid": "P" + pc, "min": p["Minutes"], "pts": p["Points"], "fgm2": p["FieldGoalsMade2"], "fga2": p["FieldGoalsAttempted2"],
                        "fgm3": p["FieldGoalsMade3"], "fga3": p["FieldGoalsAttempted3"], "ftm": p["FreeThrowsMade"], "fta": p["FreeThrowsAttempted"],
                        "oreb": p["OffensiveRebounds"], "dreb": p["DefensiveRebounds"], "reb": p["TotalRebounds"], "ast": p["Assistances"],
                        "stl": p["Steals"], "tov": p["Turnovers"], "blk": p["BlocksFavour"], "blka": p["BlocksAgainst"], "pf": p["FoulsCommited"],
                        "fd": p["FoulsReceived"], "pir": p["Valuation"], "plusminus": p.get("Plusminus")})


def gpack(g):
    return {"code": g["code"], "round": g["round"]["round"], "date": g["date"][:10], "home": g["home"]["code"], "away": g["away"]["code"],
            "hs": g["home"]["score"], "as": g["away"]["score"], "phase": g["phaseType"]["code"]}


clubs = json.load(open(os.path.join(CACHE, "clubs_src.json"))) if os.path.exists(os.path.join(CACHE, "clubs_src.json")) else cached("clubs_src.json", lambda: get(f"{FEEDS}/{SRC_SEASON}/clubs")["data"])
club = next(c for c in clubs if c["code"] == CLUB)
label = f"{SRC_SEASON[1:]}-{str(int(SRC_SEASON[1:]) + 1)[2:]}"
out = {"club": "DEMO", "season": OUT_SEASON, "demo": True,
       "club_meta": {"code": "DEMO", "name": f"Demo · {club['name']} {label}", "short": club.get("abbreviatedName") or CLUB, "country": None, "city": None,
                     "logo": f"logos/{CLUB}.png", "real_code": CLUB},
       "players": [{"pid": "P" + pc, "code": pc, "name": entry["person"]["name"], "dorsal": entry.get("dorsal"), "position": entry.get("positionName"),
                    "height": entry["person"].get("height"), "birth": (entry["person"].get("birthDate") or "")[:10],
                    "country": (entry["person"].get("country") or {}).get("name"), "photo": photo}],
       "games": [gpack(g) for g in played], "upcoming": [], "shots": shots, "box": box}
os.makedirs(os.path.join(ROOT, "data", OUT_SEASON), exist_ok=True)
json.dump(out, open(os.path.join(ROOT, "data", OUT_SEASON, "DEMO.json"), "w"))
print(f"{PLAYER}: {len(played)} games, {len(shots)} shots ({sum(s['made'] for s in shots)} made), {len(box)} box lines, photo={'yes' if photo else 'no'}")
