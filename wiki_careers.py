"""Career histories beyond the Euroleague feed: each rostered player's Wikipedia infobox, which lists every team with
years (NBA, loans and assignments, NCAA college, domestic leagues). A page is accepted only when its title carries the player's
surname and first name and its birth year matches the roster feed. Cached per season, so the league is fetched once.

usage: python wiki_careers.py E2026
"""
import json
import os
import re
import sys
import time
import unicodedata
import requests

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2026"
ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache", SEASON)
API = "https://en.wikipedia.org/w/api.php"
H = {"User-Agent": "EuroleaguePlayerLab/1.0 (https://baranerdogan11.github.io/Euroleague-Player-Lab/)"}
NBA = {"Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "New Jersey Nets", "Charlotte Hornets", "Charlotte Bobcats", "Chicago Bulls", "Cleveland Cavaliers", "Dallas Mavericks", "Denver Nuggets",
       "Detroit Pistons", "Golden State Warriors", "Houston Rockets", "Indiana Pacers", "Los Angeles Clippers", "LA Clippers", "Los Angeles Lakers", "Memphis Grizzlies", "Miami Heat", "Milwaukee Bucks",
       "Minnesota Timberwolves", "New Orleans Pelicans", "New Orleans Hornets", "New York Knicks", "Oklahoma City Thunder", "Seattle SuperSonics", "Orlando Magic", "Philadelphia 76ers", "Phoenix Suns",
       "Portland Trail Blazers", "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors", "Utah Jazz", "Washington Wizards"}
fold = lambda s: "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


def get(params):
    for attempt in range(4):
        r = requests.get(API, params={**params, "format": "json", "formatversion": 2}, headers=H, timeout=40)
        if r.ok:
            time.sleep(0.25)
            return r.json()
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"wikipedia {r.status_code}")


def wikitext(title):
    pages = get({"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "titles": title})["query"]["pages"]
    return pages[0].get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("content", "")


def birth_of(wt):
    m = re.search(r"\{\{\s*birth[ _]date(?:[ _]and[ _]age)?\s*\|(?:[^|}]*=[^|}]*\|)*\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})", wt, re.I)
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def clean(s):
    s = re.sub(r"\{\{\s*nbay\s*\|\s*(\d{4})\s*\|\s*(\d{4})[^}]*\}\}", r"\1–\2", s, flags=re.I)          # {{nbay|2013|2015}}: a span
    s = re.sub(r"\{\{\s*nbay\s*\|\s*(\d{4})[^}]*\}\}", lambda m: f"{m.group(1)}–{int(m.group(1)) + 1}", s, flags=re.I)   # {{nbay|2013}}: the 2013-14 season
    s = re.sub(r"\[\[([^|\]]*)\|([^\]]*)\]\]", r"\2", s); s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\{\{[^}]*\}\}", "", s); s = re.sub(r"<[^>]+>", "", s); s = s.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip(" *")


def spells_of(wt):
    yrs = dict(re.findall(r"\|\s*years(\d+)\s*=\s*([^\n]*)", wt)); tms = dict(re.findall(r"\|\s*team(\d+)\s*=\s*([^\n]*)", wt))
    out = []
    for k in sorted(tms, key=int):
        raw_t = tms[k]; assignment = "→" in raw_t
        t, y = clean(raw_t).strip("→ "), clean(yrs.get(k, ""))
        if not t:
            continue
        m = re.search(r"(\d{4})\s*[–\-—]\s*(\d{4}|present)", y)
        if m:
            a, b = int(m.group(1)), (None if m.group(2) == "present" else int(m.group(2)))
        else:
            m1 = re.search(r"(\d{4})", y); a = int(m1.group(1)) if m1 else None; b = a
        league = "NBA" if t in NBA else ("loan" if assignment else None)        # an arrow in the infobox marks a loan or an assignment
        out.append({"team": t, "from": a, "to": b, "league": league})
    col = re.search(r"\|\s*college\s*=\s*([^\n]*)", wt)
    college = None
    if col:
        c = clean(col.group(1)); m = re.search(r"(\d{4})\s*[–\-—]\s*(\d{4})", c)
        name = re.sub(r"\s*\(.*$", "", c).strip()
        if name:
            college = {"team": name, "from": int(m.group(1)) if m else None, "to": int(m.group(2)) if m else None, "league": "NCAA"}
    return out, college


def match(name, birth):
    """A page is the player when its title carries his surname and either his first name (birth year agreeing when both
    are known) or the exact birth date from the roster feed, which covers nicknames such as Sasha for Aleksandar."""
    norm = lambda s: re.sub(r"[^a-z0-9]", "", fold(s))
    sur, _, first = name.partition(","); sur, first = fold(re.sub(r"\s+(jr|sr|ii|iii|iv)\.?$", "", sur.strip(), flags=re.I)), fold(first.strip())
    first_tok = first.split()[0] if first else ""
    year = (birth or "")[:4]
    for q in (f"{first.title()} {sur.title()} basketball", f"{first.title()} {sur.title()}"):
        for title in [x["title"] for x in get({"action": "query", "list": "search", "srsearch": q, "srlimit": 5})["query"]["search"]]:
            if norm(sur) not in norm(title):          # hyphens, apostrophes and diacritics do not count
                continue
            wt = wikitext(title)
            if "infobox basketball biography" not in wt.lower():
                continue
            b = birth_of(wt)
            first_ok = bool(first_tok) and norm(first_tok) in norm(title) and (not year or not b or b[:4] == year)
            if not (first_ok or (b and birth and b == birth)):
                continue
            spells, college = spells_of(wt)
            if not spells:
                continue
            return {"title": title, "birth": b, "spells": spells, "college": college}
    return {"title": None}


if __name__ == "__main__":
    seen, hits, miss = set(), 0, []
    for fn in sorted(os.listdir(CACHE)):
        if not fn.startswith("roster_"):
            continue
        for p in json.load(open(os.path.join(CACHE, fn))):
            if p.get("type") != "J":
                continue
            pc = p["person"]["code"]
            if pc in seen:
                continue
            seen.add(pc)
            path = os.path.join(CACHE, f"wiki_{pc}.json")
            if os.path.exists(path):
                rec = json.load(open(path))
            else:
                try:
                    rec = match(p["person"]["name"], (p["person"].get("birthDate") or "")[:10])
                except Exception as e:
                    print("  wikipedia unavailable:", pc, e); continue
                json.dump(rec, open(path, "w"), ensure_ascii=False)
            if rec.get("title"):
                hits += 1
            else:
                miss.append(p["person"]["name"])
    print(f"{SEASON}: {hits} of {len(seen)} players matched on Wikipedia; unmatched: {', '.join(miss[:40])}{' ...' if len(miss) > 40 else ''}")
