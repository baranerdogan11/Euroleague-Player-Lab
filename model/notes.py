"""Nightly scouting notes: a short, numbers-only note per player, written by Claude from a fact sheet
built out of the warehouse and the model outputs, constrained to a JSON schema and validated before it is
stored. Only players whose fact sheet changed since the last run are regenerated.

Requires ANTHROPIC_API_KEY (or an `ant auth login` profile); without credentials the step writes nothing
and exits 0 so the pipeline still publishes.

usage: python model/notes.py E2026            # nightly
       python model/notes.py E2026 --limit 5  # try a few
"""
import datetime
import hashlib
import json
import os
import sys
import duckdb
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
from notes_checks import check_note  # noqa: E402

SEASON = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "E2026"
LIMIT = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
MODEL = os.environ.get("NOTES_MODEL", "claude-opus-5")
W = os.path.join(ROOT, "warehouse", SEASON)
OUT = os.path.join(W, "notes.parquet")
ZONES = {"rim": "at the rim", "paint": "paint (non-rim)", "mid": "mid-range", "c3": "corner 3", "a3": "above-break 3"}

SYSTEM = """You write scouting notes for a Euroleague analytics site. You receive one player's fact sheet as JSON and write
a note of two or three sentences (at most 70 words) for basketball readers.

Rules, all strict:
- Use only the numbers in the fact sheet. Every number you write must appear there, at the sheet's precision or rounded.
  Rates in the sheet are fractions; you may write them as percentages (0.523 -> 52.3%).
- Describe what the numbers show. Do not speculate about injuries, contracts, effort, character, minutes decisions or
  anything not in the sheet. Do not mention other players. Percentiles rank a player among last season's players:
  say "95th percentile", never "best in the league" or any league-wide or Europe-wide claim.
- Negative values are deficits: write "29.0 points below expectation", not a negative sign in prose.
- One paragraph, no line breaks.
- "shot_quality" is the expected points per attempt of the shots he takes; "shooting_skill_per100" is points per 100
  attempts above what a league-average shooter would score on the same shots (a skill estimate, shrunk toward zero).
  When attempts are under 100, say the sample is small.
- Lead with the most informative fact. Plain, specific prose; no bullet points, no headings.
Return JSON matching the schema."""

SCHEMA = {"type": "object", "properties": {
    "note": {"type": "string", "description": "2-3 sentences, at most 70 words"},
    "key_numbers": {"type": "array", "description": "up to four of the numbers cited, label and value", "items": {"type": "object", "properties": {"label": {"type": "string"}, "value": {"type": "string"}},
                                               "required": ["label", "value"], "additionalProperties": False}},
    "sample_caveat": {"type": "boolean", "description": "true when the note mentions a small sample"},
    "confidence": {"type": "string", "enum": ["low", "medium", "high"]}},
    "required": ["note", "key_numbers", "sample_caveat", "confidence"], "additionalProperties": False}


def zone_of(x, y, pts):
    d = (x * x + y * y) ** 0.5
    if pts == 3:
        return "c3" if y < 141.5 else "a3"
    if d < 150:
        return "rim"
    if abs(x) < 245 and y < 422.5:
        return "paint"
    return "mid"


def fact_sheets(season):
    w = os.path.join(ROOT, "warehouse", season)
    con = duckdb.connect()
    for t in ["clubs", "players", "roster_stints", "games", "box", "shots", "shots_xfg", "player_shooting"]:
        p = os.path.join(w, t + ".parquet")
        if os.path.exists(p):
            con.execute(f"create view {t} as select * from read_parquet('{p}')")
    have_prof = os.path.exists(os.path.join(w, "player_shooting.parquet"))
    q = lambda s, *a: [dict(zip([d[0] for d in con.description], r)) for r in con.execute(s, a).fetchall()]
    played = q("""select b.player, p.name, s.club, c.name as club_name, s.position,
                         count(*) gp, round(sum(b.minutes) / count(*), 1) mpg, round(sum(b.pts)::double / count(*), 1) ppg,
                         round(sum(b.reb)::double / count(*), 1) rpg, round(sum(b.ast)::double / count(*), 1) apg,
                         sum(b.fgm2) fgm2, sum(b.fga2) fga2, sum(b.fgm3) fgm3, sum(b.fga3) fga3, sum(b.ftm) ftm, sum(b.fta) fta, sum(b.pts) pts, round(sum(b.pir)::double / count(*), 1) pir
                  from box b join players p using (player)
                  join roster_stints s on s.player = b.player and s.active
                  join clubs c on c.club = s.club
                  where b.minutes > 0 group by 1,2,3,4,5""")
    sheets = []
    for r in played:
        fga = r["fga2"] + r["fga3"]
        ts = r["pts"] / (2 * (fga + 0.44 * r["fta"])) if fga + r["fta"] else None
        sheet = {"player": r["name"], "club": r["club_name"], "position": r["position"], "season": season[1:] + "-" + str(int(season[1:]) + 1)[2:],
                 "games": r["gp"], "minutes_per_game": r["mpg"], "points_per_game": r["ppg"], "rebounds_per_game": r["rpg"], "assists_per_game": r["apg"], "pir_per_game": r["pir"],
                 "two_point": {"made": r["fgm2"], "att": r["fga2"], "pct": round(r["fgm2"] / r["fga2"], 3) if r["fga2"] else None},
                 "three_point": {"made": r["fgm3"], "att": r["fga3"], "pct": round(r["fgm3"] / r["fga3"], 3) if r["fga3"] else None},
                 "free_throw": {"made": r["ftm"], "att": r["fta"], "pct": round(r["ftm"] / r["fta"], 3) if r["fta"] else None},
                 "true_shooting_pct": round(ts, 3) if ts else None}
        sh = q("select s.x, s.y, s.made, s.pts, x.xfg_ctx from shots s left join shots_xfg x using (game, seq) where s.player = ?", r["player"])
        if sh:
            zones = {}
            for s in sh:
                z = zones.setdefault(zone_of(s["x"], s["y"], s["pts"]), {"made": 0, "att": 0})
                z["att"] += 1; z["made"] += int(s["made"])
            sheet["zones"] = {ZONES[k]: {**v, "pct": round(v["made"] / v["att"], 3)} for k, v in zones.items() if v["att"] >= 5}
            scored = [s for s in sh if s["xfg_ctx"] is not None]
            if scored:
                sheet["expected"] = {"attempts": len(scored), "xfg_pct": round(sum(s["xfg_ctx"] for s in scored) / len(scored), 3),
                                     "points_above_expectation": round(sum(s["made"] * s["pts"] - s["xfg_ctx"] * s["pts"] for s in scored), 1)}
        if have_prof:
            pr = q("select att, quality_shrunk, quality_pct, skill_shrunk, skill_sd, skill_pct from player_shooting where player = ?", r["player"])
            if pr:
                p = pr[0]
                sheet["profile"] = {"attempts": p["att"], "shot_quality": round(p["quality_shrunk"], 2), "shot_quality_percentile": round(p["quality_pct"]) if p["quality_pct"] is not None else None,
                                    "shooting_skill_per100": round(100 * p["skill_shrunk"], 1), "shooting_skill_sd_per100": round(100 * p["skill_sd"], 1),
                                    "shooting_skill_percentile": round(p["skill_pct"]) if p["skill_pct"] is not None else None}
        last = q("""select g.round, g.home, g.away, g.home_score, g.away_score, b.club, b.minutes, b.pts, b.reb, b.ast, b.fgm2 + b.fgm3 as fgm, b.fga2 + b.fga3 as fga
                    from box b join games g using (game) where b.player = ? and b.minutes > 0 order by g.date desc limit 3""", r["player"])
        if last:
            l = last[0]; home = l["home"] == l["club"]; opp = l["away"] if home else l["home"]
            own, oth = (l["home_score"], l["away_score"]) if home else (l["away_score"], l["home_score"])
            sheet["last_game"] = {"round": l["round"], "opponent": opp, "home": home, "result": ("W" if own > oth else "L") + f" {own}-{oth}", "minutes": round(l["minutes"], 1),
                                  "points": l["pts"], "rebounds": l["reb"], "assists": l["ast"], "field_goals": f"{l['fgm']}/{l['fga']}"}
            if len(last) >= 3:
                sheet["last_3_games_points_per_game"] = round(sum(x["pts"] for x in last) / 3, 1)
        sheets.append({"player": r["player"], "name": r["name"], "club": r["club"], "facts": sheet})
    names = [s["name"] for s in sheets]
    return sheets, names


def structured(client, system, user, schema, max_tokens=600):
    """One structured-output call. Tries the refusal-fallback beta first; if the account or SDK rejects it,
    falls back to the plain endpoint. API errors surface with their body so a failed run is diagnosable."""
    import anthropic
    msgs = [{"role": "user", "content": user}]
    fmt = {"effort": "low", "format": {"type": "json_schema", "schema": schema}}
    try:
        resp = client.beta.messages.create(model=MODEL, max_tokens=max_tokens, system=system, messages=msgs, output_config=fmt,
                                           betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    except (anthropic.BadRequestError, TypeError) as e:
        msg = str(e).lower()
        if "fallback" in msg or "beta" in msg or "unexpected keyword" in msg:
            resp = client.messages.create(model=MODEL, max_tokens=max_tokens, system=system, messages=msgs, output_config=fmt)
        else:
            raise
    if resp.stop_reason == "refusal":
        return None, resp.usage
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text), resp.usage


def generate(client, sheet):
    return structured(client, SYSTEM, "Fact sheet:\n" + json.dumps(sheet["facts"], ensure_ascii=False), SCHEMA)


def main():
    try:
        import anthropic
        client = anthropic.Anthropic()
        client.api_key  # noqa: B018
    except Exception as e:
        print(f"notes: no Anthropic credentials or SDK ({type(e).__name__}); skipping"); return 0
    sheets, names = fact_sheets(SEASON)
    if not sheets:
        print(f"{SEASON}: no players with games yet; nothing to write"); return 0
    prev = pd.read_parquet(OUT) if os.path.exists(OUT) else pd.DataFrame(columns=["player", "facts_hash"])
    prev_hash = dict(zip(prev.player, prev.facts_hash)) if len(prev) else {}
    todo = [s for s in sheets if prev_hash.get(s["player"]) != hashlib.sha256(json.dumps(s["facts"], sort_keys=True).encode()).hexdigest()]
    if LIMIT:
        todo = todo[:LIMIT]
    print(f"{SEASON}: {len(sheets)} players with games, {len(todo)} fact sheets changed")
    rows, usage_in, usage_out = [], 0, 0
    for i, s in enumerate(todo):
        fh = hashlib.sha256(json.dumps(s["facts"], sort_keys=True).encode()).hexdigest()
        status, note, checks, out = "rejected", None, [], None
        for attempt in range(2):
            try:
                out, usage = generate(client, s)
            except Exception as e:
                name = type(e).__name__
                if name in ("AuthenticationError", "PermissionDeniedError") or "api_key" in str(e).lower() or "credential" in str(e).lower():
                    print(f"notes: no usable Anthropic credentials ({name}); skipping without changes"); return 0
                checks = [f"api error: {name}: {str(e)[:120]}"]; break
            usage_in += usage.input_tokens; usage_out += usage.output_tokens
            if out is None:
                checks = ["refused"]; break
            out["note"] = " ".join(out["note"].split())          # normalise whitespace before checking
            ok, reasons = check_note(out["note"], s["facts"], s["name"], other_names=names)
            if ok:
                status, note, checks = "ok", out, []; break
            checks = reasons
        rows.append({"player": s["player"], "facts_hash": fh, "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "model": MODEL,
                     "status": status, "note": note["note"] if note else None, "key_numbers": json.dumps(note["key_numbers"], ensure_ascii=False) if note else None,
                     "confidence": note["confidence"] if note else None, "sample_caveat": bool(note["sample_caveat"]) if note else None, "checks": json.dumps(checks)})
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(todo)} done")
    new = pd.DataFrame(rows)
    keep = prev[~prev.player.isin(new.player)] if len(prev) else prev
    allrows = pd.concat([keep, new], ignore_index=True) if len(new) else keep
    allrows.to_parquet(OUT, index=False)
    ok_n = int((new.status == "ok").sum()) if len(new) else 0
    print(f"wrote {len(new)} notes ({ok_n} ok, {len(new) - ok_n} rejected); tokens in {usage_in}, out {usage_out}; total stored {len(allrows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
