"""Proof of concept for the live check loop: scan -> rewrite -> verify -> repair.

Runs in shadow. Nothing in the product (extension, extension/api/server.py, extension/api/config.toml,
T5Rewriter) calls this module. It takes rewrites the product already made and
shows what the new pipeline would have done with them, next to what the user
sees today: every rewrite, shown with no checks and no warnings.

    1. scan     manifest(original): facts, hostile spans and requests per sentence
    2. rewrite  (already done: the product's both-t5 output is read from a CSV)
    3. verify   verify(manifest, ...): every manifest item checked in the rewrite
    4. repair   per sentence: put back a sentence whose facts changed (if it had
                no hostility), retry a sentence that is still hostile (needs a
                model; pass `retry`), otherwise return the rewrite with warnings

Facts and copies are hard checks (they block); everything else only warns,
until the human labels in new_proposed_eval.md show which checks can be trusted.

Usage:
    PYTHONPATH=src python -m secondthought.pipeline_poc research/outputs/both_detox_formalize.csv
    PYTHONPATH=src python -m secondthought.pipeline_poc --self-test
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from evaluation.evaluation import critical_value_metrics, evaluate_pair, extract_critical_values
from .sendable_gate import CONTROL_MAX_EDIT, MIN_LENGTH_RATIO, TOXICITY_MAX, gate, hostile_markers
from .t5_rewriter import split_sentences

HARD = {"copy", "fact_lost", "fact_added"}

# ponytail: verb list written while looking at the 35 dev messages, so it flatters
# them; replace with a POS tagger or an LLM once the request slots are annotated.
IMPERATIVES = {
    "add", "apologize", "ask", "book", "call", "cancel", "change", "check", "cut",
    "delete", "explain", "finish", "fix", "get", "give", "leave", "let", "make", "mark",
    "merge", "move", "pay", "put", "read", "refund", "remove", "replace", "reply",
    "restart", "review", "roll", "schedule", "send", "share", "tell", "test", "update",
    "use", "write",
}
REQUEST_CUE = re.compile(
    r"\b(?:please|needs? (?:to|it|you|those|them|that|this)|must|have to|make sure"
    r"|(?:can|could|would) you)\b",
    re.IGNORECASE,
)
DEADLINE = re.compile(
    r"\b(?:by|before|until)\s+(?:the\s+)?([\w:.]+(?:\s*[ap]\.?m\.?\b)?)|\b(today|tonight|asap)\b",
    re.IGNORECASE,
)
NOT_A_DEADLINE = {"you", "it", "we", "they", "i", "he", "she", "blaming", "then"}
VOCATIVE = re.compile(r"^(?:[A-Z][a-z]+,\s+)?(?:(?:please|just|and|so)\s+)*", re.IGNORECASE)


def _squash(text: str) -> str:
    return re.sub(r"[\s.]+", "", text.casefold())


def find_requests(sentence: str) -> list[dict[str, Any]]:
    """An ask in one sentence: its action verb (if imperative) and its deadline."""
    first = re.match(r"[a-z']+", VOCATIVE.sub("", sentence).lower())
    action = first.group() if first and first.group() in IMPERATIVES else None
    found = [(m.group(1) or m.group(2)).strip().rstrip(".,;:!?") for m in DEADLINE.finditer(sentence)]
    deadlines = [d for d in found if d and d.lower() not in NOT_A_DEADLINE]
    if not action and not deadlines and not REQUEST_CUE.search(sentence):
        return []
    return [{"action": action, "deadline": deadlines[0] if deadlines else None}]


def manifest(original: str, tone: float | None = None) -> dict[str, Any]:
    """Step 1: what must survive (facts, requests) and what must go (hostility)."""
    sentences = split_sentences(original)
    facts, hostile, requests = [], [], []
    for index, sentence in enumerate(sentences):
        facts += [{"sentence": index, "kind": v.kind, "value": v.raw} for v in extract_critical_values(sentence)]
        hostile += [{"sentence": index, "text": marker} for marker in hostile_markers(sentence)]
        requests += [{"sentence": index, **request} for request in find_requests(sentence)]
    # Skip only when BOTH the spans and the whole-message tone say polite: a
    # word-list miss must not turn into a rude message nobody rewrites.
    polite = not hostile and tone is not None and tone <= TOXICITY_MAX
    return {"sentences": sentences, "facts": facts, "hostile": hostile,
            "requests": requests, "tone": tone, "polite": polite}


def verify(m: Mapping[str, Any], rewritten: str, tone_after: float | None = None) -> list[dict[str, str]]:
    """Step 3: check every manifest item against the rewrite. Empty list = all good."""
    original = " ".join(m["sentences"])
    pair = evaluate_pair(original, rewritten)
    issues: list[dict[str, str]] = []

    def add(check: str, detail: str) -> None:
        issues.append({"check": check, "severity": "hard" if check in HARD else "soft", "detail": detail})

    if m["polite"]:
        if pair["edit_ratio"] > CONTROL_MAX_EDIT:
            add("polite_changed", "an already-polite message was rewritten")
        return issues
    if pair["exact_match"]:
        add("copy", "returned unchanged although it is hostile")
    facts = critical_value_metrics(original, rewritten)
    for value in _values(facts["critical_value_missing"]):
        add("fact_lost", value)
    for value in _values(facts["critical_value_unsupported"]):
        add("fact_added", value)
    for marker in hostile_markers(rewritten):
        add("still_hostile", marker)
    if tone_after is not None and tone_after > TOXICITY_MAX:
        add("tone", f"Detoxify {tone_after:.2f} > {TOXICITY_MAX}")
    words = set(re.findall(r"[a-z']+", rewritten.lower()))
    for request in m["requests"]:
        action, deadline = request["action"], request["deadline"]
        if action and not any(word.startswith(action.rstrip("e")) for word in words):
            add("request_dropped", f"'{action}' (sentence {request['sentence'] + 1})")
        if deadline and _squash(deadline) not in _squash(rewritten):
            add("deadline_dropped", deadline)
    if pair["length_ratio"] < MIN_LENGTH_RATIO:
        add("too_short", f"{pair['length_ratio']:.0%} of the original length")
    return issues


def _values(serialised: str) -> list[str]:
    import json
    return [value["raw"] for value in json.loads(serialised)]


def repair(
    m: Mapping[str, Any], rewritten: str, retry: Callable[[str], str] | None = None
) -> tuple[str, list[str]]:
    """Step 4: fix single sentences. Restoring is only safe for a sentence with no
    hostility; a hostile one is retried once (if a model is given), never restored."""
    before, after = m["sentences"], split_sentences(rewritten)
    if len(before) != len(after):
        return rewritten, ["sentences don't line up, so no per-sentence repair"]
    fixed, actions = list(after), []
    for index, (old, new) in enumerate(zip(before, after, strict=True)):
        facts_ok = critical_value_metrics(old, new)["critical_value_exact"]
        hostile = bool(hostile_markers(old))
        still_bad = bool(hostile_markers(new)) or (hostile and old.strip() == new.strip())
        if facts_ok and not still_bad:
            continue
        if not hostile:
            fixed[index] = old
            actions.append(f"S{index + 1}: facts changed, put back the original sentence")
        elif retry is None:
            actions.append(f"S{index + 1}: would retry (needs the model)")
        else:
            attempt = retry(old)
            good = critical_value_metrics(old, attempt)["critical_value_exact"] and not hostile_markers(attempt)
            if good:
                fixed[index] = attempt
            actions.append(f"S{index + 1}: retried, {'fixed' if good else 'still failing'}")
    return " ".join(fixed), actions


def run(
    original: str,
    rewritten: str,
    *,
    tone_before: float | None = None,
    tone_after: float | None = None,
    retry: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """The whole loop for one message. `rewritten` is the model's first attempt."""
    m = manifest(original, tone_before)
    if m["polite"]:
        return {"manifest": m, "status": "skipped", "final_text": original, "issues_before": [],
                "actions": ["looks polite already, model not called"], "warnings": []}
    issues = verify(m, rewritten, tone_after)
    if not issues:
        return {"manifest": m, "status": "pass", "final_text": rewritten, "issues_before": [],
                "actions": [], "warnings": []}
    final, actions = repair(m, rewritten, retry)
    # Detoxify isn't available for a repaired text offline, so its tone is unknown.
    warnings = verify(m, final, tone_after if final == rewritten else None)
    status = ("fixed" if not warnings
              else "blocked" if any(w["severity"] == "hard" for w in warnings) else "warned")
    return {"manifest": m, "status": status, "final_text": final, "issues_before": issues,
            "actions": actions, "warnings": warnings}


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _gate(original: str, text: str, toxicity: float | None) -> dict[str, Any]:
    row = {"original_text": original, "rewritten_text": text, **evaluate_pair(original, text)}
    if toxicity is not None:
        row["toxicity_rewritten"] = toxicity
    return gate(row)


def compare(rows: list[Mapping[str, Any]], retry: Callable[[str], str] | None = None) -> list[dict[str, Any]]:
    """Today (rewrite shown as-is) vs the POC loop, judged by the sendable gate."""
    results = []
    for row in rows:
        original, rewritten = str(row["original_text"]), str(row["rewritten_text"])
        tone_before, tone_after = _float(row.get("toxicity_original")), _float(row.get("toxicity_rewritten"))
        result = run(original, rewritten, tone_before=tone_before, tone_after=tone_after, retry=retry)
        today = _gate(original, rewritten, tone_after)
        final = result["final_text"]
        new = _gate(original, final, tone_after if final == rewritten else None)
        bad_today = not today["gate_sendable"]
        flagged = result["status"] in {"warned", "blocked"}
        if result["status"] == "skipped":
            outcome = "skipped (polite)"
        elif bad_today and result["status"] == "fixed" and new["gate_sendable"]:
            outcome = "bad today -> fixed"
        elif bad_today and flagged:
            outcome = "bad today -> now flagged"
        elif bad_today:
            outcome = "bad today -> still silent"
        elif flagged or result["status"] == "fixed":
            outcome = "gate passes -> extra flag (check by hand)"
        else:
            outcome = "good, no flag"
        results.append({
            "id": row.get("id", ""),
            "original_text": original,
            "today_text": rewritten,
            "today_user_sees": "rewrite, no warnings" if original.strip() != rewritten.strip()
                               else "'This already reads fine'",
            "today_gate": "sendable" if today["gate_sendable"] else f"NOT ({today['gate_all_failures']})",
            "poc_status": result["status"],
            "poc_text": final,
            "poc_actions": " | ".join(result["actions"]),
            "poc_warnings": " | ".join(f"{w['check']}: {w['detail']}" for w in result["warnings"]),
            "poc_gate": "sendable" if new["gate_sendable"] else f"NOT ({new['gate_all_failures']})",
            "outcome": outcome,
            "facts": ", ".join(f["value"] for f in result["manifest"]["facts"]),
            "hostile": ", ".join(h["text"] for h in result["manifest"]["hostile"]),
            "requests": ", ".join(
                " ".join(filter(None, [r["action"], r["deadline"] and f"by {r['deadline']}"])) or "(ask)"
                for r in result["manifest"]["requests"]),
        })
    return results


def report(path: Path, out_dir: Path | None) -> None:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    results = compare(rows)
    print(f"\n{path.name}: {len(rows)} messages")
    for outcome, count in sorted(Counter(r["outcome"] for r in results).items()):
        print(f"  {outcome:42} {count:>3}")
    today = sum(r["today_gate"] == "sendable" for r in results)
    print(f"  gate-sendable today {today}/{len(rows)}; shown with a warning by the POC "
          f"{sum(r['poc_status'] in ('warned', 'blocked') for r in results)}")
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{path.stem}_poc.csv"
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
        print(f"  wrote {target}")


def self_test() -> None:
    message = "Did you even test this? This stupid retry loop hits the API 20 times. @sara needs it fixed by Friday."
    m = manifest(message, tone=0.9)
    assert [f["value"] for f in m["facts"]] == ["API", "20 times", "@sara", "Friday"], m["facts"]
    assert [h["text"] for h in m["hostile"]] == ["Did you even", "stupid"], m["hostile"]
    assert m["requests"] == [{"sentence": 2, "action": None, "deadline": "Friday"}], m["requests"]

    good = "Was this tested? This retry loop hits the API 20 times. @sara needs it fixed by Friday."
    assert run(message, good, tone_before=0.9)["status"] == "pass"

    # A fact changed in a sentence with no hostility: put that sentence back.
    result = run(message, good.replace("by Friday", "by Monday"), tone_before=0.9)
    assert result["status"] == "fixed" and result["final_text"] == good, result

    # Still hostile: retried when a model is given, otherwise warned. Never restored.
    leftover = "Did you even test this? This retry loop hits the API 20 times. @sara needs it fixed by Friday."
    assert run(message, leftover, tone_before=0.9)["status"] == "warned"
    fixed = run(message, leftover, tone_before=0.9, retry=lambda s: "Was this tested?")
    assert fixed["status"] == "fixed" and fixed["final_text"] == good, fixed

    # A copy of a hostile message is blocked, not shown as "already reads fine".
    assert run(message, message, tone_before=0.9)["status"] == "blocked"

    # A dropped deadline that is a fact ("Friday") is put back above; one that
    # isn't ("before merging") can't be, so it only warns.
    dropped = run("This stupid loop is slow. Replace it before merging.",
                  "This loop is slow. Please replace it.", tone_before=0.9)
    assert dropped["status"] == "warned", dropped
    assert "deadline_dropped" in [w["check"] for w in dropped["warnings"]], dropped

    # Polite input: skipped only when the spans AND the tone agree.
    polite = "This function drops failed records. Please add error handling before approving."
    assert run(polite, "anything", tone_before=0.01)["status"] == "skipped"
    assert run(polite, polite, tone_before=None)["status"] != "skipped"
    print("pipeline_poc self-test: 8/8 cases behaved as expected")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--out", type=Path, help="write <name>_poc.csv here")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test or not args.files:
        self_test()
    for path in args.files:
        report(path, args.out)


if __name__ == "__main__":
    main()
