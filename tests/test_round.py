"""When a round is over: build.round_state decides whether the latest round with a final still has games to play, which the cover
needs to name the game of the round only at the end of the round. A game moved past the next round's start, or more than a week
past the round's last final when no later round is scheduled, is postponed and does not hold the round open.

build.py runs the whole build on import, so the function is lifted out of its source.
usage: python tests/test_round.py
"""
import ast
import datetime
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "build.py"), encoding="utf-8").read()
fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "round_state")
ns = {"datetime": datetime}
exec(compile(ast.Module([fn], []), "build.py", "exec"), ns)
round_state = ns["round_state"]

g = lambda code, rnd, date: {"game": code, "round": rnd, "date": date, "home": "AAA", "away": "BBB"}
played = [g(1, 11, "2026-11-12"), g(2, 11, "2026-11-13"), g(3, 12, "2026-11-17")]

# mid-round: the rest of round 12 is due, so the round is open and Next lists it
rest, nxt, still = round_state(played, [g(4, 12, "2026-11-17"), g(5, 12, "2026-11-18"), g(6, 13, "2026-11-24")])
assert still and [r[0] for r in rest] == [4, 5] and [r[0] for r in nxt] == [4, 5], (rest, nxt, still)

# every game final: the round is over and Next moves on
rest, nxt, still = round_state(played, [g(6, 13, "2026-11-24"), g(7, 13, "2026-11-25")])
assert not still and rest == [] and [r[0] for r in nxt] == [6, 7], (rest, nxt, still)

# one game postponed past the next round's start: over, but the game is kept for the board
rest, nxt, still = round_state(played, [g(4, 12, "2026-12-09"), g(6, 13, "2026-11-24")])
assert not still and [r[0] for r in rest] == [4] and [r[0] for r in nxt] == [6], (rest, nxt, still)

# a game on the next round's first day still counts as part of this round
rest, nxt, still = round_state(played, [g(4, 12, "2026-11-24"), g(6, 13, "2026-11-24")])
assert still, (rest, nxt, still)

# no later round scheduled: a week after the round's last final is the limit
assert round_state(played, [g(4, 12, "2026-11-24")])[2]
assert not round_state(played, [g(4, 12, "2026-11-25")])[2]
assert round_state(played, []) == ([], [], False)
print("round state: 7 cases ok")
