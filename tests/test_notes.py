"""Offline tests for the scouting-note validators (no API): what must pass and what must be rejected.

usage: python tests/test_notes.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
from notes_checks import check_note, numbers_in  # noqa: E402

facts = {"player": "VEZENKOV, SASHA", "club": "Olympiacos", "games": 34, "minutes_per_game": 29.4, "points_per_game": 16.8,
         "three_point": {"made": 68, "att": 172, "pct": 0.395}, "two_point": {"made": 121, "att": 214, "pct": 0.565}, "true_shooting_pct": 0.631,
         "expected": {"attempts": 386, "xfg_pct": 0.467, "points_above_expectation": 37.4},
         "profile": {"attempts": 386, "shot_quality": 1.1, "shot_quality_percentile": 58, "shooting_skill_per100": 8.0, "shooting_skill_sd_per100": 4.3, "shooting_skill_percentile": 95},
         "last_game": {"round": 12, "opponent": "MAD", "result": "W 84-80", "points": 22, "field_goals": "8/13"}}
others = ["VEZENKOV, SASHA", "WALKUP, THOMAS", "MIROTIC, NIKOLA"]

cases = {
    "faithful note passes": ("Vezenkov is scoring 16.8 points in 29.4 minutes over 34 games, hitting 39.5% from three on 172 attempts. His shooting skill sits at +8.0 points per 100 attempts (95th percentile), with 37.4 points above expectation on 386 shots.", True),
    "percentage form of a rate passes": ("He shoots 56.5% inside the arc and 39.5% from three, a 63.1% true shooting mark across 34 games.", True),
    "invented number is rejected": ("Vezenkov averages 21.3 points and shoots 44% from three over 34 games this season, an elite mark.", False),
    "banned claim (injury) is rejected": ("After returning from injury he is scoring 16.8 points per game over 34 games with 39.5% from three.", False),
    "other player mention is rejected": ("Like Mirotic, he scores 16.8 points per game over 34 games and hits 39.5% of his threes.", False),
    "too long is rejected": (" ".join(["He scores 16.8 points per game over 34 games."] * 12), False),
    "too short is rejected": ("Good shooter, 39.5% from three.", False),
}
ok_all = True
for name, (note, want) in cases.items():
    ok, reasons = check_note(note, facts, facts["player"], other_names=others)
    passed = ok == want
    ok_all &= passed
    print(("PASS " if passed else "FAIL ") + name + ("" if passed else f"  -> got {ok}, reasons {reasons}"))
extract = numbers_in("16.8 points, 39.5% from three, 8/13 in R12, +8.0 per 100")
passed = sorted(extract) == sorted([16.8, 39.5, 8.0, 13.0, 8.0, 100.0])   # "R12" is a label, not a cited number
ok_all &= passed
print(("PASS " if passed else "FAIL ") + f"number extraction ({extract})")
print("ALL PASS" if ok_all else "FAILED")
sys.exit(0 if ok_all else 1)
