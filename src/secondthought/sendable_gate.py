"""Prototype "sendable gate" from data/workplace_eval/new_proposed_eval.md.

A rewrite is sendable only if it passes every check. Each check returns True
(pass), False (fail) or None (not measured yet). The first failure is the
headline reason, but every check's result is kept so no failure is hidden.

Implemented: controls left unchanged, 1 not a copy, 2 facts intact, 3 hostility gone (Detoxify when
scored, plus a phrase list), 5 nothing lost (length only). Checks 4 (intent)
and 6 (nothing added, fluent) are not built yet, so every verdict is
provisional. All thresholds are placeholders until fitted to human labels.

Usage:
    python -m secondthought.sendable_gate research/outputs/both_detox_formalize.csv ...
    python -m secondthought.sendable_gate --self-test
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .evaluation import evaluate_pair

# ponytail: uncalibrated placeholders; fit them on the human labels (proposal, "Calibration").
TOXICITY_MAX = 0.2   # Detoxify score above this counts as still hostile.
MIN_LENGTH_RATIO = 0.75  # Shorter than this suggests a clause was deleted, not rephrased.
CONTROL_MAX_EDIT = 0.1   # A non-hostile input must come back nearly unchanged.

# Workplace hostility that Detoxify misses. Copied from extension/frontend/triggers.js,
# which was written while looking at the 35-message dev set, so it flatters that set.
# ponytail: word list; replace with a trained or LLM-judge hostility score.
HOSTILE_WORDS = {
    "damn", "dammit", "crap", "crappy", "shit", "shitty", "bullshit", "shitshow",
    "fuck", "fucking", "fucked", "wtf", "ass", "asshole", "bloody", "bitch", "pissed",
    "idiot", "idiots", "idiotic", "stupid", "dumb", "moron", "moronic", "useless",
    "pathetic", "ridiculous", "garbage", "trash", "lazy", "incompetent", "jerk",
    "clueless", "brainless", "sloppy", "screwup", "nonsense", "whining", "loser",
    "clown", "smug",
}
HOSTILE_PHRASES = re.compile(
    r"\b(?:(?:what|who|where|why|how) the hell|as hell|shut up|screw(?:ed|ing)? (?:up|around)"
    r"|out of your ass|did you even|stop ignoring|(?:is|was|are) a (?:joke|disaster|mess)"
    r"|know-it-all)\b",
    re.IGNORECASE,
)

CHECKS = (
    "control_unchanged", "not_copy", "facts_intact", "hostility_gone",
    "intent_kept", "nothing_lost", "nothing_added",
)


def _bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def hostile_markers(text: str) -> list[str]:
    words = [word for word in re.findall(r"[a-z']+", text.lower()) if word in HOSTILE_WORDS]
    return words + [match.group() for match in HOSTILE_PHRASES.finditer(text)]


def gate(row: Mapping[str, Any]) -> dict[str, Any]:
    """Judge one evaluated row (a line of an *_evaluated.csv, or evaluate_pair output plus texts)."""
    original, rewritten = str(row["original_text"]), str(row["rewritten_text"])
    toxicity = _float(row.get("toxicity_rewritten"))
    checks: dict[str, bool | None] = dict.fromkeys(CHECKS)

    # Controls are labelled in the dataset ("control": true), never guessed:
    # firm but polite inputs look the same as hostile ones to a word list.
    if _bool(row.get("control")):
        checks["control_unchanged"] = (_float(row.get("edit_ratio")) or 0.0) <= CONTROL_MAX_EDIT
    else:
        checks["not_copy"] = not _bool(row.get("exact_match"))
        ratio = _float(row.get("length_ratio"))
        checks["nothing_lost"] = None if ratio is None else ratio >= MIN_LENGTH_RATIO
    checks["facts_intact"] = _bool(row.get("critical_value_exact"))
    checks["hostility_gone"] = not hostile_markers(rewritten) and not (
        toxicity is not None and toxicity > TOXICITY_MAX
    )

    failed = [name for name in CHECKS if checks[name] is False]
    return {
        **{f"gate_{name}": checks[name] for name in CHECKS},
        "gate_sendable": not failed,
        "gate_reason": failed[0] if failed else "",
        "gate_all_failures": ";".join(failed),
        "gate_hostile_markers": ";".join(hostile_markers(rewritten)),
    }


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if not total:
        return (0.0, 0.0)
    p = successes / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return (centre - half, centre + half)


def report(path: Path, out_dir: Path | None) -> None:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    verdicts = [gate(row) for row in rows]
    sendable = sum(v["gate_sendable"] for v in verdicts)
    low, high = wilson(sendable, len(rows))
    print(f"\n{path.name}: {sendable}/{len(rows)} sendable "
          f"({sendable / len(rows):.0%}, 95% CI {low:.0%}-{high:.0%})")
    if "toxicity_rewritten" not in rows[0]:
        print("  note: no Detoxify scores in this file; hostility uses the phrase list only")
    failures = Counter(name for v in verdicts for name in v["gate_all_failures"].split(";") if name)
    for name in CHECKS:
        measured = any(v[f"gate_{name}"] is not None for v in verdicts)
        print(f"  {name:15} {failures[name] if measured else 'not measured':>3}")
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{path.stem}_gate.csv"
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=[*rows[0], *verdicts[0]])
            writer.writeheader()
            writer.writerows({**row, **v} for row, v in zip(rows, verdicts))
        print(f"  wrote {target}")


def _judge(original: str, rewritten: str, control: bool = False) -> dict[str, Any]:
    row = {"original_text": original, "rewritten_text": rewritten, "control": control}
    return gate({**row, **evaluate_pair(original, rewritten)})


def self_test() -> None:
    """Known failures from our runs, plus faults injected into a good rewrite."""
    known = [  # (original, rewritten, expected headline reason; "" = sendable)
        ("Did you even test this? This stupid retry loop hits the API 20 times. Replace it before merging.",
         "Was this tested? This retry loop hits the API 20 times. Please replace it before merging.", ""),
        ("Did you even test this? This stupid retry loop hits the API 20 times. Replace it before merging.",
         "Did you even test this? This stupid retry loop hits the API 20 times. Replace it before merging.",
         "not_copy"),
        ("That report is garbage. The defect rate went from 2.5% to 4%, and you called that an improvement.",
         "That report is not good. The defect rate went from 2,5% to 4%, and you called that an improvement.",
         "facts_intact"),
        ("Did you even test this? This stupid retry loop hits the API 20 times. Replace it before merging.",
         "Did you even test this? This retry loop hits the API 20 times. Replace it before merging.",
         "hostility_gone"),
        ("What a ridiculous pile of nonsense. Remove the made-up claims from the proposal before it goes out.",
         "Remove the made-up claims.", "nothing_lost"),
    ]
    controls = [  # Already-professional inputs, labelled control=True.
        ("This function silently drops failed records. Please add error handling before approving the pull request.",
         "This function silently drops failed records. Please add error handling before approving the pull request.",
         ""),
        ("This function silently drops failed records. Please add error handling before approving the pull request.",
         "Great work overall! Maybe consider adding some error handling at some point, if you have time.",
         "control_unchanged"),
    ]
    gaps = [  # Failures the prototype cannot catch yet; they should flip once checks 3-6 are built.
        ("I'm sick of your bullshit excuses, Daniel. The client needs those 6 drawings by Friday.",
         "I'm sick of your excuses, Daniel. The client needs those 6 drawings by Friday.", "hostility_gone"),
        ("This rollout is a complete shitshow. Roll it back before 5 PM.",
         "This rollout is a complete show. Roll it back before 5 PM.", "nothing_lost"),
        ("Stop ignoring me and send the report by 5 PM today.",
         "Sorry to bother you! Whenever you get a chance, could you send the report by 5 PM today?",
         "intent_kept"),
    ]
    for original, rewritten, expected in known:
        got = _judge(original, rewritten)["gate_reason"]
        assert got == expected, f"expected {expected or 'sendable'!r}, got {got or 'sendable'!r}: {rewritten}"
    for original, rewritten, expected in controls:
        got = _judge(original, rewritten, control=True)["gate_reason"]
        assert got == expected, f"control: expected {expected or 'sendable'!r}, got {got or 'sendable'!r}"
    print(f"known failures: {len(known) + len(controls)}/{len(known) + len(controls)} judged as expected")
    for original, rewritten, expected in gaps:
        got = _judge(original, rewritten)["gate_reason"]
        print(f"  known gap ({expected} not built): judged {got or 'sendable'!r} -> {rewritten}")

    original, good = known[0][0], known[0][1]
    faults = {
        "not_copy": original,
        "facts_intact": good.replace("20", "30"),
        "hostility_gone": good.replace("This retry", "This stupid retry"),
        "nothing_lost": "Please replace it before merging.",
    }
    assert _judge(original, good)["gate_sendable"], "the clean rewrite must pass"
    for check, broken in faults.items():
        verdict = _judge(original, broken)
        assert verdict[f"gate_{check}"] is False, f"{check} missed injected fault: {broken}"
    print(f"fault injection: {len(faults)}/{len(faults)} injected faults caught by their check")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", nargs="*", type=Path, help="evaluated CSVs (from secondthought evaluate)")
    parser.add_argument("--out", type=Path, help="folder for per-row *_gate.csv files")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test or not args.csv:
        self_test()
    for path in args.csv:
        report(path, args.out)
    print("\nProvisional: intent_kept and nothing_added are not measured; thresholds are uncalibrated.")


if __name__ == "__main__":
    main()
