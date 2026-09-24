"""Deterministic checks for generated scouting notes. No API, no SDK: the tests run these offline.

A note passes when every number it cites can be traced to the fact sheet (at the sheet's own precision or
a coarser rounding), it stays within length, it makes no claims from a banned vocabulary (injuries,
contracts, character), and it names no player other than the subject.
"""
import re

MAX_WORDS = 80
BANNED = ["injur", "contract", "salary", "transfer", "trade", "rumor", "rumour", "agent", "locker", "attitude", "character", "lazy", "clutch gene",
          "mvp", "all-star", "nba", "best in europe", "worst in europe", "sign", "extension", "coach said", "reportedly"]


def numbers_in(text):
    """Every number in the text as float, with percentages kept as their percentage value."""
    out = []
    for m in re.finditer(r"(?<![\w.])[-+]?\d+(?:[.,]\d+)?(?=%|\b)", text):
        s = m.group(0).replace(",", ".")
        try:
            out.append(float(s))
        except ValueError:
            pass
    return out


def allowed_numbers(facts):
    """Set of numbers a note may cite: each numeric fact at its own precision and at 0 and 1 decimals,
    rates also as percentages (0.523 -> 52.3, 52), and per-game values from totals where provided."""
    allowed = {2.0, 3.0, 40.0, 100.0}          # unit words: 2-point, 3-point, per 40, per 100

    def add(v):
        if v is None or isinstance(v, bool):
            return
        if isinstance(v, str):                    # numbers embedded in strings: "5/12", "W 84-80", "R12"
            for n in numbers_in(v):
                add(n)
            return
        if isinstance(v, (int, float)):
            v = abs(v)                            # "29.0 points below expectation" cites -29.0 as a magnitude
            for r in (v, round(v, 1), round(v, 0), round(v, 2)):
                allowed.add(round(r, 3))
            if 0 <= v <= 1.0:                     # a rate: also allow its percentage form
                for r in (100 * v, round(100 * v, 1), round(100 * v, 0)):
                    allowed.add(round(r, 3))
            if isinstance(v, float) and v > 1 and v == int(v):
                allowed.add(float(int(v)))

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
        else:
            add(x)
    walk(facts)
    return allowed


def check_note(note, facts, subject_name, other_names=()):
    """Returns (ok, list of failure reasons)."""
    reasons = []
    if "\n" in note.strip() or "  " in note:
        reasons.append("formatting: line breaks or double spaces inside the note")
    for phrase in ("in the league", "in europe", "league-best", "league-worst", "best in", "worst in"):
        if phrase in note.lower():
            reasons.append(f"unsupported league-wide claim: '{phrase}'")
    for sent in re.split(r"(?<=[.!?])\s+", note):        # grading words need the number that supports them in the same sentence
        low_s = sent.lower()
        for adj in ("elite", "excellent", "outstanding", "superb", "strong", "poor", "weak", "terrible", "dominant"):
            if re.search(r"\b" + adj + r"\b", low_s) and not re.search(r"\d", sent):
                reasons.append(f"ungrounded adjective: '{adj}'")
    words = len(note.split())
    if words > MAX_WORDS:
        reasons.append(f"too long: {words} words > {MAX_WORDS}")
    if words < 15:
        reasons.append(f"too short: {words} words")
    low = note.lower()
    for b in BANNED:
        if b in low:
            reasons.append(f"banned term: '{b}'")
    allowed = allowed_numbers(facts)
    for n in numbers_in(note):
        m = abs(n)                                # signs are carried by the prose ("below expectation")
        if not any(abs(m - a) <= max(0.051, 0.006 * abs(a)) for a in allowed):
            reasons.append(f"untraceable number: {n:g}")
    sur = subject_name.split(",")[0].strip().lower() if subject_name else ""
    for name in other_names:
        s = name.split(",")[0].strip().lower()
        if s and s != sur and len(s) > 3 and re.search(r"\b" + re.escape(s) + r"\b", low):
            reasons.append(f"mentions another player: {s}")
    return (not reasons), reasons
