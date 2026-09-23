"""Evaluation of the scouting-note generator on a fixed set of fact sheets.

The set (model/notes_eval_set.jsonl) is 30 players sampled deterministically from the reference season
(100+ attempts). For each, the generator produces a note; the report scores:
  1. automated checks (schema, length, numeric faithfulness, banned claims, other-player mentions)
  2. an LLM judge (separate prompt) rating factual faithfulness and usefulness 1-5 and listing any claim
     the fact sheet does not support
  3. agreement with human labels where the jsonl has a `human_ok` field filled in (true/false)
Writes model/notes_eval.json and the generated notes back into the jsonl for annotation.

usage: python model/notes_eval.py --build E2025    # (re)build the evaluation set from a season warehouse
       python model/notes_eval.py                  # run the evaluation (needs Anthropic credentials)
"""
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
from notes_checks import check_note  # noqa: E402

SET = os.path.join(ROOT, "model", "notes_eval_set.jsonl")
REPORT = os.path.join(ROOT, "model", "notes_eval.json")
JUDGE_MODEL = os.environ.get("NOTES_JUDGE_MODEL", "claude-opus-5")
JUDGE_SYSTEM = """You are auditing a basketball scouting note against the fact sheet it was written from.
Score two things from 1 (poor) to 5 (excellent):
- faithfulness: every claim and number is supported by the fact sheet; no invented context, no unsupported comparisons.
- usefulness: a basketball reader learns the most informative things in the sheet, stated clearly.
List every claim that the fact sheet does not support (empty list if none). Return JSON matching the schema."""
JUDGE_SCHEMA = {"type": "object", "properties": {"faithfulness": {"type": "integer", "enum": [1, 2, 3, 4, 5]}, "usefulness": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                                                 "unsupported_claims": {"type": "array", "items": {"type": "string"}}},
                "required": ["faithfulness", "usefulness", "unsupported_claims"], "additionalProperties": False}


def build(season, n=30, seed=7):
    import notes
    notes.SEASON = season
    sheets, names = notes.fact_sheets(season)
    eligible = [s for s in sheets if s["facts"].get("profile", {}).get("attempts", 0) >= 100]
    random.Random(seed).shuffle(eligible)
    with open(SET, "w") as f:
        for s in eligible[:n]:
            f.write(json.dumps({"player": s["player"], "name": s["name"], "facts": s["facts"], "note": None, "human_ok": None}, ensure_ascii=False) + "\n")
    print(f"evaluation set: {min(n, len(eligible))} players from {season} written to {SET}")


def run():
    import anthropic
    import notes
    client = anthropic.Anthropic()
    items = [json.loads(l) for l in open(SET)]
    names = [i["name"] for i in items]
    results = []
    for it in items:
        out, usage = notes.generate(client, {"facts": it["facts"], "name": it["name"]})
        if out is None:
            results.append({"player": it["player"], "name": it["name"], "note": None, "auto_ok": False, "auto_reasons": ["refused"]}); continue
        ok, reasons = check_note(out["note"], it["facts"], it["name"], other_names=names)
        notes.MODEL = JUDGE_MODEL
        judge, _ = notes.structured(client, JUDGE_SYSTEM, f"Fact sheet:\n{json.dumps(it['facts'], ensure_ascii=False)}\n\nNote:\n{out['note']}", JUDGE_SCHEMA, max_tokens=500)
        notes.MODEL = os.environ.get("NOTES_MODEL", "claude-opus-5")
        it["note"] = out["note"]
        results.append({"player": it["player"], "name": it["name"], "note": out["note"], "confidence": out["confidence"], "auto_ok": ok, "auto_reasons": reasons,
                        "judge": judge, "human_ok": it.get("human_ok")})
    with open(SET, "w") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    n = len(results)
    judged = [r for r in results if r.get("judge")]
    labelled = [r for r in results if r.get("human_ok") is not None]
    report = {"n": n, "generator": notes.MODEL, "judge": JUDGE_MODEL,
              "auto_pass_rate": round(sum(r["auto_ok"] for r in results) / n, 3),
              "judge_faithfulness_mean": round(sum(r["judge"]["faithfulness"] for r in judged) / len(judged), 2) if judged else None,
              "judge_usefulness_mean": round(sum(r["judge"]["usefulness"] for r in judged) / len(judged), 2) if judged else None,
              "judge_faithful_5_rate": round(sum(r["judge"]["faithfulness"] == 5 for r in judged) / len(judged), 3) if judged else None,
              "unsupported_claims_total": sum(len(r["judge"]["unsupported_claims"]) for r in judged),
              "human_labelled": len(labelled),
              "human_pass_rate": round(sum(r["human_ok"] for r in labelled) / len(labelled), 3) if labelled else None,
              "judge_human_agreement": round(sum((r["judge"]["faithfulness"] >= 4) == r["human_ok"] for r in labelled if r.get("judge")) / len(labelled), 3) if labelled else None,
              "results": results}
    json.dump(report, open(REPORT, "w"), indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=1))


if __name__ == "__main__":
    if "--build" in sys.argv:
        build(sys.argv[sys.argv.index("--build") + 1])
    else:
        try:
            run()
        except Exception as e:
            import traceback
            body = getattr(e, "body", None) or getattr(getattr(e, "response", None), "text", None)
            msg = f"notes_eval failed: {type(e).__name__}: {e}\n{body if body else ''}\n{traceback.format_exc()}"
            print(msg)
            if os.environ.get("GITHUB_STEP_SUMMARY"):
                open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("### Scouting notes evaluation failed\n```\n" + msg[-3000:] + "\n```\n")
            sys.exit(1)
