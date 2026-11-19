"""The game's best player on the cover always comes from the winning club: build.game_star ranks only the winner's lines by
PIR, then points, then name, even when a player on the losing side had the bigger night.

build.py runs the whole build on import, so the function is lifted out of its source.
usage: python tests/test_star.py
"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "build.py"), encoding="utf-8").read()
fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "game_star")
ns = {}
exec(compile(ast.Module([fn], []), "build.py", "exec"), ns)
game_star = ns["game_star"]

b = lambda name, club, pir, pts, minutes=20.0: {"name": name, "club": club, "pir": pir, "pts": pts, "minutes": minutes}
lines = [b("LOSER, BIG", "AAA", 35, 30), b("WINNER, ONE", "BBB", 22, 18), b("WINNER, TWO", "BBB", 22, 20), b("WINNER, DNP", "BBB", 0, 0, None)]

# the away club won: the loser's 35 PIR line is passed over, and the tie on PIR goes to points
star = game_star({"home": "AAA", "away": "BBB", "home_score": 80, "away_score": 84}, lines)
assert star["name"] == "WINNER, TWO", star

# the home club won: its best line is the loser's above
star = game_star({"home": "AAA", "away": "BBB", "home_score": 90, "away_score": 84}, lines)
assert star["name"] == "LOSER, BIG", star

# a tie on PIR and points goes to the name, as on the game page
star = game_star({"home": "AAA", "away": "BBB", "home_score": 80, "away_score": 84}, [b("ZETA, A", "BBB", 10, 10), b("ALPHA, B", "BBB", 10, 10)])
assert star["name"] == "ALPHA, B", star

# no winner's player with minutes: nobody is named
assert game_star({"home": "AAA", "away": "BBB", "home_score": 80, "away_score": 84}, [b("X, Y", "BBB", 5, 5, 0)]) is None

print("game star: 4 checks passed")
