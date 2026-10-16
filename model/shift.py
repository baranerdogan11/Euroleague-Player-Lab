"""How much a retrained xFG model moves a season's numbers: compares two shots_xfg files shot by shot and player by
player on the context-only expectation (the one every "expected" figure on the site uses). Prints Markdown.

usage: python model/shift.py E2026 old_shots_xfg.parquet [new_shots_xfg.parquet]   # new defaults to the warehouse file
"""
import os
import sys
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEASON, OLD = sys.argv[1], sys.argv[2]
W = os.path.join(ROOT, "warehouse", SEASON)
NEW = sys.argv[3] if len(sys.argv) > 3 else os.path.join(W, "shots_xfg.parquet")
MIN_ATT = 50

con = duckdb.connect()
con.execute(f"""create view j as
    select s.player, s.zone, s.pts, s.made::int made, o.xfg_ctx x_old, n.xfg_ctx x_new
    from read_parquet('{W}/shots.parquet') s
    join read_parquet('{OLD}') o using (game, seq) join read_parquet('{NEW}') n using (game, seq)""")
shot = con.execute("""select count(*), avg(abs(x_new - x_old)) * 100, quantile_cont(abs(x_new - x_old), 0.9) * 100, max(abs(x_new - x_old)) * 100,
                             avg(x_old) * 100, avg(x_new) * 100, avg(made) * 100 from j""").fetchone()
print(f"### {SEASON}: {shot[0]:,} shots\n")
print(f"- Per shot, xFG% moved {shot[1]:.1f} points on average (90% of shots within {shot[2]:.1f}, largest {shot[3]:.1f}).")
print(f"- League xFG% {shot[4]:.1f} before, {shot[5]:.1f} after; actual FG% {shot[6]:.1f}.\n")
print("| Zone | Shots | xFG% before | xFG% after | FG% |\n|---|---:|---:|---:|---:|")
for z in con.execute("select zone, count(*), avg(x_old) * 100, avg(x_new) * 100, avg(made) * 100 from j group by 1 order by 1").fetchall():
    print(f"| {z[0]} | {z[1]:,} | {z[2]:.1f} | {z[3]:.1f} | {z[4]:.1f} |")
pl = con.execute(f"""select any_value(coalesce(p."name", j.player)) pname, count(*) att, avg(x_old) * 100 xo, avg(x_new) * 100 xn,
                            (sum(made * pts) - sum(x_new * pts)) / count(*) * 100 - (sum(made * pts) - sum(x_old * pts)) / count(*) * 100 dskill
                     from j left join read_parquet('{W}/players.parquet') p using (player)
                     group by j.player having count(*) >= {MIN_ATT} order by abs(xn - xo) desc""").fetchall()
if pl:
    mean_abs = sum(abs(r[3] - r[2]) for r in pl) / len(pl)
    print(f"\nPlayers with {MIN_ATT}+ attempts: {len(pl)}. Their xFG% moved {mean_abs:.1f} points on average.\n")
    print("| Player | Att | xFG% before | xFG% after | Skill change per 100 |\n|---|---:|---:|---:|---:|")
    for r in pl[:8]:
        print(f"| {r[0]} | {r[1]} | {r[2]:.1f} | {r[3]:.1f} | {r[4]:+.1f} |")
