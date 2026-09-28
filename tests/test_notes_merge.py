"""The notes merge must survive a run with nothing to regenerate (the crash that failed every nightly run from
26 September) and must replace only the players a run rewrote."""
import os
import sys
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
import notes  # noqa: E402

prev = pd.DataFrame([{"player": "1", "facts_hash": "a", "status": "ok"}, {"player": "2", "facts_hash": "b", "status": "rejected"}])
empty = pd.DataFrame(columns=["player", "facts_hash", "status"])

assert len(notes.merge_notes(prev, [])) == 2, "an empty run keeps the stored notes"
assert len(notes.merge_notes(empty, [])) == 0, "nothing stored and nothing new is fine"
m = notes.merge_notes(empty, [{"player": "9", "facts_hash": "z", "status": "ok"}])
assert list(m.player) == ["9"], "first run writes its rows"
m = notes.merge_notes(prev, [{"player": "2", "facts_hash": "c", "status": "ok"}, {"player": "3", "facts_hash": "d", "status": "ok"}])
assert sorted(m.player) == ["1", "2", "3"] and m[m.player == "2"].facts_hash.iloc[0] == "c", "a rewrite replaces only its players"
assert m[m.player == "1"].status.iloc[0] == "ok", "untouched players keep their note"
print("ALL PASS")

# a change in the league benchmarks alone must not trigger a rewrite; a change in the player's own facts must
f1 = {"games": 1, "points_per_game": 12.0, "league_benchmarks": {"true_shooting_pct": 0.571}}
f2 = {"games": 1, "points_per_game": 12.0, "league_benchmarks": {"true_shooting_pct": 0.574}}
f3 = {"games": 2, "points_per_game": 14.5, "league_benchmarks": {"true_shooting_pct": 0.574}}
assert notes.facts_hash(f1) == notes.facts_hash(f2), "benchmarks alone do not change the hash"
assert notes.facts_hash(f1) != notes.facts_hash(f3), "the player's own facts do"
print("ALL PASS")
