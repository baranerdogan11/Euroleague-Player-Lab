"""Build-to-build plausibility of the leaders file (teams/<season>/leaders.json).

The gates validate each build on its own; this compares a build with the one before it. A club's games never go
backwards, a player's games played never go backwards, and no season total moves by more than the new games can
explain (CAP a game). A change with no new game, or a total going down, is a box-score correction: a warning.
More than a tenth of the player lines vanishing is a failure (a roster feed replaced by an empty one), fewer a warning.

check(old, new) -> (failures, warnings), lists of sentences; build.py writes them to drift.json and stops on a failure.
"""
CAP = {"pts": 60, "reb": 30, "ast": 25, "min": 48, "fga2": 40, "fga3": 30, "fta": 30}   # the most one game can add to a season total


def check(old, new):
    if not old or not old.get("rows"):
        return [], []
    fails, warns = [], []
    og, ng = old.get("games") or {}, new.get("games") or {}
    for c, n in sorted(og.items()):
        if ng.get(c, 0) < n:
            fails.append(f"{c}: games {n} -> {ng.get(c, 0)}")
    orow = {(r["pid"], r["c"]): r for r in old["rows"]}
    nrow = {(r["pid"], r["c"]): r for r in new["rows"]}
    gone = [f"{r['name']} ({r['c']})" for k, r in orow.items() if k not in nrow]
    if gone:
        (fails if len(gone) > max(3, len(orow) // 10) else warns).append(f"{len(gone)} player line(s) gone: " + ", ".join(gone[:8]))
    for k, o in orow.items():
        n = nrow.get(k)
        if not n:
            continue
        who = f"{n['name']} ({n['c']})"
        add = n["gp"] - o["gp"]
        if add < 0:
            fails.append(f"{who}: games played {o['gp']} -> {n['gp']}")
            continue
        for stat, cap in CAP.items():
            d = (n.get(stat) or 0) - (o.get(stat) or 0)
            if abs(d) > max(add, 1) * cap:
                fails.append(f"{who}: {stat} {o.get(stat)} -> {n.get(stat)} with {add} new game(s)")
            elif (add == 0 and abs(d) > 0.05) or d < -0.05:
                warns.append(f"{who}: {stat} corrected {o.get(stat)} -> {n.get(stat)} ({add} new game(s))")
    return fails, warns
