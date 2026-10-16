"""Proves the win probability model (winprob.py) reads a game the right way round.

A synthetic game: the home club leads all night, the feed appends a late correction with an earlier clock (as the live feed
does), and the away club scores last. Asserts the states follow the game clock, the score never runs backwards, a bigger
lead or more time gone means a higher chance for the leader, a tie at the buzzer is close to even, and the chart starts at
the pregame figure and ends on the winner. Also checks the committed coefficients point the right way.
usage: python tests/test_winprob.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import winprob

M = winprob.load()
assert M and len(M["coef"]) == len(winprob.FEATURES), "model/winprob.json missing or out of date: run python winprob.py"
coef = M["coef"]
assert coef[0] > 0 and coef[1] > 0 and coef[2] > 0, f"margin, home court and strength must all favour the club they describe: {coef}"

e = lambda seq, per, club, pt, clk, h=None, a=None: {"seq": seq, "period": per, "club": club, "playtype": pt, "clock_sec": clk, "score_home": h, "score_away": a}
evs = [e(1, 1, None, "BP", None), e(2, 1, "H", "2FGM", 580, 2), e(3, 1, "A", "D", 560), e(4, 1, "A", "TO", 550),
       e(5, 4, "H", "3FGM", 120, 5, None), e(6, 4, "A", "2FGM", 60, 5, 2),
       e(9, 2, "H", "FTM", 300, 3, None)]                     # a late correction: seq after the fourth quarter, clock in the second
S = winprob.states(evs, "H", "A")
assert [s[0] for s in S] == sorted(s[0] for s in S), f"states must follow the game clock: {S}"
assert [s[3] for s in S] == [2, 2, 2, 3, 5, 3], f"margins: {[s[3] for s in S]}"
assert S[1][4] == -1 and S[2][4] == 1, f"the ball after a defensive rebound and a turnover: {S}"

p = lambda m, f: winprob.prob(coef, m, f, 0, 0)
assert p(5, 0.5) > p(2, 0.5) > p(0, 0.5) > p(-2, 0.5), "a bigger lead must mean a better chance"
assert p(5, 0.05) > p(5, 0.5), "the same lead must be worth more late"
assert abs(p(0, winprob.F_MIN) - 0.5) < 0.03, f"a tie at the buzzer is close to even: {p(0, winprob.F_MIN)}"

c = winprob.curve(coef, evs, {"home": "H", "away": "A", "home_score": 5, "away_score": 2, "strength": 0})
assert c["len"] == 2400 and len(c["v"]) == 2400 // winprob.STEP + 1 == len(c["m"]), "one value every STEP seconds plus the final"
assert c["v"][0] == round(1000 * winprob.prob(coef, 0, 1, 0, 0)) and c["v"][-1] == 1000 and c["m"][-1] == 3, f"start {c['v'][0]}, end {c['v'][-1]}"
assert all(0 <= v <= 1000 for v in c["v"])
print("win probability self-test: PASS")
