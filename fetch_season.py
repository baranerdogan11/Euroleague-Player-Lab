"""Pull a whole Euroleague season for the app: every club's crest, roster and photos, plus per-game shots
with court coordinates and box scores for games already played. Cached under cache/<season>/ so each rerun
only fetches games (and players) that are new.

usage: python fetch_season.py E2026
"""
import io
import json
import os
import sys
import time
import requests
from PIL import Image

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2026"
NO_PHOTOS = "--no-photos" in sys.argv   # past seasons: stats and shots only
ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache", SEASON)
DATA = os.path.join(ROOT, "data", SEASON)
PHOTOS = os.path.join(ROOT, "photos")
LOGOS = os.path.join(ROOT, "logos")
for d in (CACHE, DATA, PHOTOS, LOGOS):
    os.makedirs(d, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
FEEDS = "https://feeds.incrowdsports.com/provider/euroleague-feeds/v2/competitions/E/seasons"
LIVE = "https://live.euroleague.net/api"
PHOTO_H = 480


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


SOURCES = os.path.join(PHOTOS, "sources.json")   # image file -> feed URL it was built from
sources = json.load(open(SOURCES)) if os.path.exists(SOURCES) else {}


def save_image(url, out_path, height=None, fmt="WEBP"):
    """Download, downscale, write as webp (photos) or png (crests). Skipped while the feed still points at the
    same URL; a new URL (this season's media-day photo replacing last season's) is fetched again."""
    key = os.path.relpath(out_path, ROOT)
    if os.path.exists(out_path) and sources.get(key) == url:
        return True
    try:
        raw = get(url, as_json=False)
    except Exception as e:
        print("   image failed:", url, e)
        return os.path.exists(out_path)
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    if height and im.height > height:
        im = im.resize((int(im.width * height / im.height), height), Image.LANCZOS)
    if fmt == "WEBP":
        im.save(out_path, "WEBP", quality=80, method=6)
    else:
        im.save(out_path, "PNG", optimize=True)
    sources[key] = url
    json.dump(sources, open(SOURCES, "w"), indent=0, sort_keys=True)
    return True


# ---- clubs and crests
clubs = cached("clubs.json", lambda: get(f"{FEEDS}/{SEASON}/clubs")["data"])
index = []
for c in clubs:
    crest = (c.get("images") or {}).get("crest")
    ok = save_image(crest, os.path.join(LOGOS, f"{c['code']}.png"), height=160, fmt="PNG") if (crest and not NO_PHOTOS) else os.path.exists(os.path.join(LOGOS, f"{c['code']}.png"))
    index.append({"code": c["code"], "name": c["name"], "short": c.get("abbreviatedName") or c["name"], "country": (c.get("country") or {}).get("name"),
                  "city": c.get("city"), "logo": f"logos/{c['code']}.png" if ok else None})
index.sort(key=lambda c: c["name"])
print(f"{SEASON}: {len(index)} clubs")

# ---- fallback photos: previous seasons' rosters, for players whose media-day image is not published yet
prev_photo = {}
for back in ((1, 2) if not NO_PHOTOS else ()):
    ps = f"E{int(SEASON[1:]) - back}"
    try:
        pclubs = cached(f"prev_clubs_{ps}.json", lambda: get(f"{FEEDS}/{ps}/clubs")["data"])
        for pc in pclubs:
            ppl = cached(f"prev_roster_{ps}_{pc['code']}.json", lambda: (lambda j: j["data"] if isinstance(j, dict) else j)(get(f"{FEEDS}/{ps}/clubs/{pc['code']}/people", {"personType": "J"})))
            for p in ppl:
                url = (p.get("images") or {}).get("headshot") or (p.get("images") or {}).get("action")
                if url and p["person"]["code"] not in prev_photo:
                    prev_photo[p["person"]["code"]] = url
    except Exception as e:
        print("previous-season rosters unavailable:", ps, e)
print(f"fallback photos available for {len(prev_photo)} players from earlier seasons")

# ---- games (all, once per run so newly played games are picked up)
games = get(f"{FEEDS}/{SEASON}/games", {"limit": 500})["data"]
json.dump(games, open(os.path.join(CACHE, "games_latest.json"), "w"))
played_all = [g for g in games if (g["home"]["score"] or 0) + (g["away"]["score"] or 0) > 0]
print(f"games: {len(games)} scheduled, {len(played_all)} played")

for club in index:
    code = club["code"]
    print(f"\n== {club['name']} ({code})")
    # roster + photos
    # rosters are re-pulled every run so registrations, departures and end dates stay current
    roster = (lambda j: j["data"] if isinstance(j, dict) else j)(get(f"{FEEDS}/{SEASON}/clubs/{code}/people", {"personType": "J"}))
    json.dump(roster, open(os.path.join(CACHE, f"roster_{code}.json"), "w"))
    players = []
    for p in roster:
        if p.get("type") != "J":
            continue
        pc = p["person"]["code"]
        url = (p.get("images") or {}).get("headshot") or (p.get("images") or {}).get("action") or prev_photo.get(pc)
        has_photo = save_image(url, os.path.join(PHOTOS, f"{pc}.webp"), height=PHOTO_H) if (url and not NO_PHOTOS) else os.path.exists(os.path.join(PHOTOS, f"{pc}.webp"))
        players.append({"pid": "P" + pc, "code": pc, "name": p["person"]["name"], "dorsal": p.get("dorsal"), "position": p.get("positionName"),
                        "height": p["person"].get("height"), "birth": (p["person"].get("birthDate") or "")[:10],
                        "country": (p["person"].get("country") or {}).get("name"), "photo": f"photos/{pc}.webp" if has_photo else None})
    print(f"   roster {len(players)}, photos {sum(1 for p in players if p['photo'])}")

    team_games = sorted([g for g in games if code in (g["home"]["code"], g["away"]["code"])], key=lambda g: g["date"])
    played = [g for g in team_games if (g["home"]["score"] or 0) + (g["away"]["score"] or 0) > 0]
    upcoming = [g for g in team_games if g not in played][:3]

    shots, box = [], []
    for g in played:
        gc = g["code"]
        rows = cached(f"points_{gc}.json", lambda: get(f"{LIVE}/Points", {"gamecode": gc, "seasoncode": SEASON})["Rows"])
        home, away = g["home"]["code"], g["away"]["code"]
        for r in rows:
            act = r["ID_ACTION"].strip()
            if r["TEAM"].strip() != code or act not in ("2FGM", "2FGA", "3FGM", "3FGA"):
                continue
            shots.append({"game": gc, "pid": r["ID_PLAYER"].strip(), "x": r["COORD_X"], "y": r["COORD_Y"], "made": act.endswith("M"),
                          "pts": 3 if act.startswith("3") else 2, "zone": r["ZONE"].strip(), "q": r["MINUTE"], "clock": r["CONSOLE"],
                          "fastbreak": r["FASTBREAK"] == "1", "second_chance": r["SECOND_CHANCE"] == "1"})
        cached(f"pbp_{gc}.json", lambda: get(f"{LIVE}/PlayByPlay", {"gamecode": gc, "seasoncode": SEASON}))   # events: assists, fouls, blocks, substitutions, clock
        j = cached(f"box_{gc}.json", lambda: get(f"{LIVE}/Boxscore", {"gamecode": gc, "seasoncode": SEASON}))
        for side in j.get("Stats", []):
            for p in side.get("PlayersStats", []):
                if p.get("Team", "").strip() != code:
                    continue
                box.append({"game": gc, "pid": p["Player_ID"].strip(), "min": p["Minutes"], "pts": p["Points"], "fgm2": p["FieldGoalsMade2"], "fga2": p["FieldGoalsAttempted2"],
                            "fgm3": p["FieldGoalsMade3"], "fga3": p["FieldGoalsAttempted3"], "ftm": p["FreeThrowsMade"], "fta": p["FreeThrowsAttempted"],
                            "oreb": p["OffensiveRebounds"], "dreb": p["DefensiveRebounds"], "reb": p["TotalRebounds"], "ast": p["Assistances"],
                            "stl": p["Steals"], "tov": p["Turnovers"], "blk": p["BlocksFavour"], "blka": p["BlocksAgainst"], "pf": p["FoulsCommited"],
                            "fd": p["FoulsReceived"], "pir": p["Valuation"], "plusminus": p.get("Plusminus")})
    print(f"   games played {len(played)}, shots {len(shots)}, box lines {len(box)}")

    def gpack(g):
        return {"code": g["code"], "round": g["round"]["round"], "date": g["date"][:10], "home": g["home"]["code"], "away": g["away"]["code"],
                "hs": g["home"]["score"], "as": g["away"]["score"], "phase": g["phaseType"]["code"]}
    json.dump({"club": code, "season": SEASON, "players": players, "games": [gpack(g) for g in played], "upcoming": [gpack(g) for g in upcoming],
               "shots": shots, "box": box}, open(os.path.join(DATA, f"{code}.json"), "w"))

json.dump({"season": SEASON, "clubs": index}, open(os.path.join(DATA, "clubs.json"), "w"), ensure_ascii=False)
print("\ndone")
