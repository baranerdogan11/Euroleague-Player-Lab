"""SQL assertions over the silver layer. Exits non-zero if any fails.

usage: python warehouse_tests.py E2026
       python warehouse_tests.py E2022 --no-lineups   # past seasons kept only for xFG training: the lineup layer is not used or kept
"""
import os
import sys
import duckdb

SEASON = sys.argv[1] if len(sys.argv) > 1 else "E2026"
ROOT = os.path.dirname(os.path.abspath(__file__))
W = os.path.join(ROOT, "warehouse", SEASON)
con = duckdb.connect()
for t in ["clubs", "players", "roster_stints", "games", "box", "shots"]:
    con.execute(f"create view {t} as select * from read_parquet('{os.path.join(W, t + '.parquet')}')")
for t in ["events", "shot_context"]:      # play-by-play layer, present once events.py has run
    p = os.path.join(W, t + ".parquet")
    con.execute(f"create view {t} as select * from read_parquet('{p}')" if os.path.exists(p) else f"create view {t} as select null::int game, null::int seq, null::varchar club, null::varchar playtype where false")
p = os.path.join(W, "stints.parquet")      # lineup layer (lineups.py)
con.execute(f"create view stints as select * from read_parquet('{p}')" if os.path.exists(p) else "create view stints as select null::int game, null::varchar club, null::int stint, null::varchar[] players, null::int sec, null::int pts, null::int opp_pts where false")
p = os.path.join(W, "oncourt.parquet")
con.execute(f"create view oncourt as select * from read_parquet('{p}')" if os.path.exists(p) else "create view oncourt as select null::int game, null::varchar player, null::varchar club, null::int sec, null::double box_min where false")

N_CLUBS = {"E2022": 18, "E2023": 18, "E2024": 18}.get(SEASON, 20)   # past seasons kept for xFG training had 18 clubs
N_RS = 2 * (N_CLUBS - 1)                                             # double round robin

# (name, query returning the number of offending rows)
TESTS = [
    (f"clubs: {N_CLUBS} rows, unique codes", f"select abs(count(*) - {N_CLUBS}) + (count(*) - count(distinct club)) from clubs"),
    ("players: unique codes, non-empty names", "select count(*) - count(distinct player) + sum(case when name is null or name = '' then 1 else 0 end) from players"),
    ("roster_stints: player exists", "select count(*) from roster_stints s left join players p using (player) where p.player is null"),
    ("roster_stints: club exists", "select count(*) from roster_stints s left join clubs c using (club) where c.club is null"),
    ("roster_stints: start before end", "select count(*) from roster_stints where start_date is not null and end_date is not null and start_date > end_date"),
    ("roster_stints: at most one active stint per player", "select count(*) from (select player from roster_stints where active group by player having count(*) > 1)"),
    ("roster_stints: every club has 8 to 40 active players", "select count(*) from (select club, count(*) n from roster_stints where active group by club having n < 8 or n > 40)"),
    ("games: unique codes", "select count(*) - count(distinct game) from games"),
    ("games: both clubs known", "select count(*) from games g left join clubs h on h.club = g.home left join clubs a on a.club = g.away where h.club is null or a.club is null"),
    ("games: played games have a score", "select count(*) from games where played and coalesce(home_score, 0) + coalesce(away_score, 0) = 0"),
    ("games: played games are not in the future", "select count(*) from games where played and date > current_date"),
    (f"games: each club plays {N_RS} regular-season games", f"select count(*) from (select c.club, sum(case when g.phase = 'RS' then 1 else 0 end) n from clubs c join games g on c.club in (g.home, g.away) group by c.club having n != {N_RS})"),
    ("box: game exists and was played", "select count(*) from box b left join games g using (game) where g.game is null or not g.played"),
    ("box: club is one of the game's clubs", "select count(*) from box b join games g using (game) where b.club not in (g.home, g.away)"),
    ("box: one line per player per game", "select count(*) - count(distinct (game, player)) from box"),
    ("box: makes never exceed attempts", "select count(*) from box where fgm2 > fga2 or fgm3 > fga3 or ftm > fta"),
    ("box: points reconcile with makes", "select count(*) from box where pts != 2 * fgm2 + 3 * fgm3 + ftm"),
    ("shots: game exists and was played", "select count(*) from shots s left join games g using (game) where g.game is null or not g.played"),
    ("shots: club is one of the game's clubs", "select count(*) from shots s join games g using (game) where s.club not in (g.home, g.away)"),
    ("shots: coordinates inside the court", "select count(*) from shots where x < -800 or x > 800 or y < -200 or y > 1450"),
    ("shots: attempts reconcile with box score per player per game", """
        select count(*) from (
          select b.game, b.player, b.fga2 + b.fga3 as box_att, count(s.game) as plotted
          from box b left join shots s on s.game = b.game and s.player = b.player
          group by b.game, b.player, b.fga2, b.fga3 having box_att != plotted)"""),
    ("shots: makes reconcile with box score per player per game", """
        select count(*) from (
          select b.game, b.player, b.fgm2 + b.fgm3 as box_made, coalesce(sum(case when s.made then 1 else 0 end), 0) as plotted
          from box b left join shots s on s.game = b.game and s.player = b.player
          group by b.game, b.player, b.fgm2, b.fgm3 having box_made != plotted)"""),
    ("shots: every shooter has a box line", "select count(*) from (select distinct game, player from shots) s left join box b using (game, player) where b.player is null"),
    ("events: game exists and was played", "select count(*) from (select distinct game from events) e left join games g using (game) where g.game is null or not g.played"),
    ("events: assists per club per game reconcile with the box score", """
        select count(*) from (
          select e.game, e.club, count(*) filter (where e.playtype = 'AS') as a, (select sum(ast) from box b where b.game = e.game and b.club = e.club) as b
          from events e where e.club is not null group by e.game, e.club having a != b)"""),
    ("events: every shot in a game with play-by-play has a context row", "select count(*) from shots s left join shot_context c using (game, seq) where s.game in (select distinct game from events) and c.game is null"),
    ("stints: five players on the floor in every stint", "select count(*) from stints where len(players) != 5"),
    ("stints: points per club per game reconcile with the final score", """
        select count(*) from (select s.game, s.club, sum(s.pts) p from stints s group by 1, 2) x join games g using (game)
        where x.p != case when x.club = g.home then g.home_score else g.away_score end"""),
    ("stints: both clubs cover the whole game (40 minutes plus overtimes, within 5 seconds)", "select count(*) from (select game, club, sum(sec) s from stints group by 1, 2) x where s < 2395 or least((s - 2400) % 300, 300 - (s - 2400) % 300) > 5"),
    ("oncourt: reconstructed minutes agree with the box score within three minutes", "select count(*) from oncourt where abs(sec / 60.0 - box_min) > 3.0"),
]
# warnings: reported and counted, never fail the run
WARNINGS = [
    ("roster_stints: no club has more than 22 active players (youth registrations are legitimate)", "select count(*) from (select club, count(*) n from roster_stints where active group by club having n > 22)"),
    # the play-by-play and the box score are two feeds; a substitution clocked a minute off in one of them is a feed error, not ours
    ("oncourt: reconstructed minutes agree with the box score within a minute", "select count(*) from oncourt where abs(sec / 60.0 - box_min) > 1.0"),
    ("shots: shot value consistent with distance (3s from 6.4 m out, 2s inside 7 m)", "select count(*) from shots where (pts = 3 and sqrt(x*x + y*y) < 640) or (pts = 2 and sqrt(x*x + y*y) > 700)"),
]
if "--no-lineups" in sys.argv:   # older substitution logs do not always reconstruct five on the floor; nothing built from them is kept
    TESTS = [t for t in TESTS if not t[0].startswith(("stints:", "oncourt:"))]
    WARNINGS = [t for t in WARNINGS if not t[0].startswith(("stints:", "oncourt:"))]
warned = []   # each warning that fired, by name with its row count, so status.json says what to look at, not only how many
for name, q in WARNINGS:
    n = con.execute(q).fetchone()[0] or 0
    print(("PASS " if n == 0 else "WARN ") + name + ("" if n == 0 else f"  ({n} rows)"))
    if n:
        warned.append({"check": name, "rows": n})
warn = len(warned)
bad = 0
for name, q in TESTS:
    n = con.execute(q).fetchone()[0] or 0
    print(("PASS " if n == 0 else "FAIL ") + name + ("" if n == 0 else f"  ({n} offending rows)"))
    bad += n != 0
stats = {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in ["clubs", "players", "roster_stints", "games", "box", "shots"]}
played = con.execute("select count(*) from games where played").fetchone()[0]
import datetime, json
json.dump({"season": SEASON, "checked_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "clubs": stats["clubs"], "players": stats["players"],
           "games": played, "shots": stats["shots"], "box_lines": stats["box"], "tests": len(TESTS), "failures": bad, "warnings": warn, "warning_list": warned, "ok": bad == 0},
          open(os.path.join(W, "status.json"), "w"), indent=1)
print("rows:", stats)
print("RESULT:", "OK" if not bad else f"{bad} test(s) failed")
sys.exit(0 if not bad else 1)
