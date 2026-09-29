"""Offline metrics for saved professional-rewrite predictions.

Toxicity and semantic similarity are optional learned evaluators and are imported
lazily. Critical-value preservation is implemented locally and accepts either
automatically extracted values or human-authored annotations.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any, Protocol

WORD_PATTERN = re.compile(r"\b[\w']+\b", re.UNICODE)

# Ordered from most to least specific. Later matches may not overlap earlier ones,
# so "$1,000" is one money value rather than money plus a generic number.
URL_PATTERN = re.compile(r"\b(?:https?://|www\.)[^\s<>]+", re.I)
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
MENTION_PATTERN = re.compile(r"(?<![\w@])@[A-Za-z0-9_]{1,64}\b")
TICKET_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,11}-\d+\b")
ISO_DATE_PATTERN = re.compile(r"\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b")
SLASH_DATE_PATTERN = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-](?:\d{2}|\d{4})\b")
MONTH_DATE_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
    r"Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+(?:19|20)\d{2})?\b", re.I
)
RELATIVE_DATE_PATTERN = re.compile(
    r"\b(?:today|tomorrow|tonight|yesterday|"
    r"(?:(?:this|next|last)\s+)?(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday))\b",
    re.I,
)
TIME_PATTERN = re.compile(
    r"\b(?:(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[ap]\.?m\.?)?|"
    r"(?:1[0-2]|0?[1-9])(?:\s*:\s*[0-5]\d)?\s*[ap]\.?m\.?|noon|midnight)\b",
    re.I,
)
MONEY_PATTERN = re.compile(
    r"(?<!\w)(?:(?P<symbol>[$€£¥])\s*(?P<symbol_amount>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)|"
    r"(?P<code>USD|EUR|GBP|JPY)\s*(?P<code_amount>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?))\b",
    re.I,
)
PERCENT_PATTERN = re.compile(
    r"(?<!\w)(?P<amount>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+|\.\d+)(?:\.\d+)?)"
    r"\s*(?:%|percent(?:age)?\b)", re.I
)
MEASUREMENT_PATTERN = re.compile(
    r"(?<![\w.])(?P<amount>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+|\.\d+)(?:\.\d+)?)\s*"
    r"(?P<unit>milliseconds?|msecs?|ms|seconds?|secs?|minutes?|mins?|hours?|hrs?|"
    r"days?|weeks?|months?|years?|bytes?|kilobytes?|kb|megabytes?|mb|gigabytes?|gb|"
    r"terabytes?|tb|hz|khz|mhz|ghz|meters?|metres?|cm|mm|km|inches?|feet|ft|"
    r"pounds?|lbs?|kilograms?|kg|grams?|requests?|records?|files?|entries?|times?|calls?)\b",
    re.I,
)
NUMBER_WORD_MEASUREMENT_PATTERN = re.compile(
    r"\b(?P<word_amount>(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)"
    r"(?:[ -]+(?:and[ -]+)?(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand))*)\s+"
    r"(?P<unit>milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|years?|"
    r"bytes?|kilobytes?|megabytes?|gigabytes?|terabytes?|meters?|metres?|inches?|"
    r"feet|pounds?|kilograms?|grams?|requests?|records?|files?|entries?|times?|calls?)\b",
    re.I,
)
NUMBER_PATTERN = re.compile(
    r"(?<![\w.])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+|\.\d+)(?:\.\d+)?(?![\w.])"
)
ACRONYM_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]{1,15}\b")
CAMEL_IDENTIFIER_PATTERN = re.compile(
    r"\b(?:[a-z]+[A-Z][A-Za-z0-9]*|[A-Z][a-z]+(?:[A-Z][A-Za-z0-9]*)+)\b"
)
NUMBER_WORD_PATTERN = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
    r"forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|first|second|third|"
    r"fourth|fifth|sixth|seventh|eighth|ninth|tenth|once|twice|thrice)"
    r"(?:[ -]+(?:and[ -]+)?(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand))*\b",
    re.I,
)

_SMALL_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "once": 1, "twice": 2, "thrice": 3,
}
_CURRENCIES = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
_UNITS = {
    "millisecond": "ms", "milliseconds": "ms", "msec": "ms", "msecs": "ms",
    "second": "s", "seconds": "s", "sec": "s", "secs": "s",
    "minute": "min", "minutes": "min", "mins": "min",
    "hour": "h", "hours": "h", "hr": "h", "hrs": "h",
    "byte": "byte", "bytes": "byte", "kilobyte": "kb", "kilobytes": "kb",
    "megabyte": "mb", "megabytes": "mb", "gigabyte": "gb", "gigabytes": "gb",
    "terabyte": "tb", "terabytes": "tb", "meter": "m", "meters": "m",
    "metre": "m", "metres": "m", "inch": "in", "inches": "in",
    "foot": "ft", "feet": "ft", "pound": "lb", "pounds": "lb", "lbs": "lb",
    "kilogram": "kg", "kilograms": "kg", "gram": "g", "grams": "g",
    "request": "request", "requests": "request", "record": "record", "records": "record",
    "file": "file", "files": "file", "entry": "entry", "entries": "entry",
    "time": "time", "times": "time", "day": "day", "days": "day",
    "call": "time", "calls": "time",
    "week": "week", "weeks": "week", "month": "month", "months": "month",
    "year": "year", "years": "year",
}


@dataclass(frozen=True)
class CriticalValue:
    kind: str
    raw: str
    normalized: str
    start: int | None = None
    end: int | None = None


class ToxicityScorer(Protocol):
    def score(self, texts: Sequence[str]) -> list[float]: ...


class SimilarityScorer(Protocol):
    def score_pairs(self, pairs: Sequence[tuple[str, str]]) -> list[float]: ...


class DetoxifyToxicityScorer:
    """External learned classifier; scores require workplace-domain calibration."""

    def __init__(self, model_type: str = "original", device: str = "cpu") -> None:
        try:
            from detoxify import Detoxify
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install evaluators with: pip install -e '.[evaluation]'") from exc
        self.model_name = f"detoxify:{model_type}"
        self._model = Detoxify(model_type, device=device)

    def score(self, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        values = self._model.predict(list(texts))["toxicity"]
        return [float(value) for value in values]


class SentenceTransformerSimilarityScorer:
    """External learned encoder; cosine similarity is not proof of preserved intent."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-mpnet-base-v2",
        device: str = "cpu",
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install evaluators with: pip install -e '.[evaluation]'") from exc
        self.model_name = model_name
        self._model = SentenceTransformer(model_name, device=device)

    def score_pairs(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        left = self._model.encode(
            [p[0] for p in pairs], batch_size=32, convert_to_numpy=True,
            normalize_embeddings=True,
        )
        right = self._model.encode(
            [p[1] for p in pairs], batch_size=32, convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return [float((a * b).sum()) for a, b in zip(left, right, strict=True)]


def _decimal_string(value: str) -> str:
    try:
        number = Decimal(value.replace(",", ""))
    except InvalidOperation:
        return value.casefold().strip()
    if number == 0:
        number = abs(number)
    return format(number.normalize(), "f")


def _number_word_value(raw: str) -> int:
    total = current = 0
    for word in re.split(r"[ -]+", raw.casefold()):
        if word == "and":
            continue
        if word in _ORDINALS:
            current += _ORDINALS[word]
        elif word in _SMALL_NUMBERS:
            current += _SMALL_NUMBERS[word]
        elif word == "hundred":
            current = max(current, 1) * 100
        elif word == "thousand":
            total += max(current, 1) * 1000
            current = 0
    return total + current


def _normalize_time(raw: str) -> str:
    value = re.sub(r"[.\s]", "", raw.casefold())
    if value == "noon":
        return "12:00"
    if value == "midnight":
        return "00:00"
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?([ap]m)?", value)
    if not match:
        return value
    hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), match.group(3)
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def _normalize_date(raw: str) -> str:
    value = raw.casefold().replace(",", "").strip()
    iso = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value)
    if iso:
        return f"{int(iso.group(1)):04d}-{int(iso.group(2)):02d}-{int(iso.group(3)):02d}"
    named = re.fullmatch(r"([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?", value)
    if named:
        month_names = {
            "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
            "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7,
            "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
            "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
            "dec": 12, "december": 12,
        }
        month = month_names.get(named.group(1))
        if month:
            year = named.group(3) or "----"
            return f"{year}-{month:02d}-{int(named.group(2)):02d}"
    return re.sub(r"\s+", " ", value)


def _normalize(kind: str, match: re.Match[str]) -> str:
    raw = match.group(0).strip().rstrip(".,;:!?")
    if kind == "number":
        return _decimal_string(raw)
    if kind == "number_word":
        return str(_number_word_value(raw))
    if kind == "percentage":
        return _decimal_string(match.group("amount"))
    if kind == "money":
        currency = _CURRENCIES.get(match.group("symbol"), (match.group("code") or "").upper())
        amount = match.group("symbol_amount") or match.group("code_amount")
        return f"{currency}:{_decimal_string(amount)}"
    if kind == "measurement":
        unit = match.group("unit").casefold()
        amount = match.groupdict().get("amount")
        normalized_amount = (
            _decimal_string(amount)
            if amount is not None
            else str(_number_word_value(match.group("word_amount")))
        )
        return f"{normalized_amount}:{_UNITS.get(unit, unit)}"
    if kind == "time":
        return _normalize_time(raw)
    if kind in {"email", "mention", "url", "relative_date"}:
        return raw.casefold()
    if kind in {"ticket_id", "acronym"}:
        return raw.upper()
    if kind in {"iso_date", "slash_date", "month_date"}:
        return _normalize_date(raw)
    return re.sub(r"[,\s]+", " ", raw.casefold()).strip()


def extract_critical_values(text: str) -> list[CriticalValue]:
    """Extract reliable structured values without using another model."""

    patterns = [
        ("url", URL_PATTERN), ("email", EMAIL_PATTERN), ("mention", MENTION_PATTERN),
        ("ticket_id", TICKET_PATTERN), ("iso_date", ISO_DATE_PATTERN),
        ("slash_date", SLASH_DATE_PATTERN), ("month_date", MONTH_DATE_PATTERN),
        ("relative_date", RELATIVE_DATE_PATTERN), ("time", TIME_PATTERN),
        ("money", MONEY_PATTERN), ("percentage", PERCENT_PATTERN),
        ("measurement", MEASUREMENT_PATTERN),
        ("measurement", NUMBER_WORD_MEASUREMENT_PATTERN), ("number", NUMBER_PATTERN),
        ("number_word", NUMBER_WORD_PATTERN), ("identifier", CAMEL_IDENTIFIER_PATTERN),
        ("acronym", ACRONYM_PATTERN),
    ]
    values: list[CriticalValue] = []
    occupied: list[tuple[int, int]] = []
    for kind, pattern in patterns:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < old_end and old_start < end for old_start, old_end in occupied):
                continue
            raw = match.group(0).strip().rstrip(".,;:!?")
            if raw:
                values.append(CriticalValue(kind, raw, _normalize(kind, match), start, start + len(raw)))
                occupied.append((start, end))
    return sorted(values, key=lambda value: (value.start or 0, value.end or 0))


def coerce_critical_values(
    values: str | Sequence[str | Mapping[str, Any]] | None,
) -> list[CriticalValue] | None:
    """Parse an optional JSON/Python list of human-authored critical values."""

    if values is None or values == "":
        return None
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except json.JSONDecodeError as exc:
            raise ValueError("critical_values must be valid JSON") from exc
        if not isinstance(values, list):
            raise ValueError("critical_values JSON must contain a list")
    result: list[CriticalValue] = []
    for entry in values:
        if isinstance(entry, str):
            result.append(CriticalValue("annotated", entry, entry.casefold().strip()))
        elif isinstance(entry, Mapping):
            raw = str(entry.get("value", entry.get("raw", ""))).strip()
            if not raw:
                raise ValueError("each critical value object needs value or raw")
            kind = str(entry.get("type", entry.get("kind", "annotated"))).strip()
            normalized = str(entry.get("normalized", raw.casefold())).strip()
            result.append(CriticalValue(kind, raw, normalized))
        else:
            raise ValueError("each critical value must be a string or object")
    return result


def _value_key(value: CriticalValue) -> tuple[str, str]:
    # Digits and number words are equivalent, e.g. "two" and "2".
    if value.kind == "measurement" and value.normalized.rsplit(":", 1)[-1] in {
        "request", "record", "file", "entry", "time"
    }:
        # Count nouns are often legitimately paraphrased ("20 times" -> "20 API
        # calls"). Preserve the amount here; annotate the noun when it is itself a
        # critical fact.
        kind, normalized = "number", value.normalized.rsplit(":", 1)[0]
        return kind, normalized
    if value.kind in {"number", "number_word"}:
        kind = "number"
    elif value.kind in {"iso_date", "slash_date", "month_date"}:
        kind = "date"
    else:
        kind = value.kind
    return kind, value.normalized


def _annotation_is_present(value: CriticalValue, rewritten: str) -> bool:
    extracted = extract_critical_values(rewritten)
    if any(_value_key(candidate) == _value_key(value) for candidate in extracted):
        return True
    normalized_rewrite = re.sub(r"\s+", " ", rewritten.casefold()).strip()
    normalized_raw = re.sub(r"\s+", " ", value.raw.casefold()).strip()
    return normalized_raw in normalized_rewrite


def critical_value_metrics(
    original: str,
    rewritten: str,
    annotated_values: str | Sequence[str | Mapping[str, Any]] | None = None,
) -> dict[str, int | float | bool | str]:
    """Compute duplicate-aware preservation and newly introduced value counts."""

    annotations = coerce_critical_values(annotated_values)
    automatic_source = extract_critical_values(original)
    source = annotations if annotations is not None else automatic_source
    output = extract_critical_values(rewritten)

    preserved: list[CriticalValue] = []
    missing: list[CriticalValue] = []
    if annotations is not None:
        for value in source:
            (preserved if _annotation_is_present(value, rewritten) else missing).append(value)
    else:
        remaining = Counter(_value_key(value) for value in output)
        for value in source:
            key = _value_key(value)
            if remaining[key] > 0:
                remaining[key] -= 1
                preserved.append(value)
            else:
                missing.append(value)

    # Unsupported values use all automatically extracted source values, because a
    # human annotation list may intentionally include only the most important ones.
    unmatched = Counter(_value_key(value) for value in output)
    for key, count in Counter(_value_key(value) for value in automatic_source).items():
        unmatched[key] -= min(count, unmatched[key])
    unsupported: list[CriticalValue] = []
    for value in output:
        key = _value_key(value)
        if unmatched[key] > 0:
            unsupported.append(value)
            unmatched[key] -= 1

    total = len(source)
    recall = len(preserved) / total if total else 1.0
    return {
        "critical_value_count": total,
        "critical_value_preserved_count": len(preserved),
        "critical_value_recall": round(recall, 4),
        "critical_value_missing_count": len(missing),
        "critical_value_unsupported_count": len(unsupported),
        "critical_value_exact": not missing and not unsupported,
        "critical_value_missing": json.dumps(
            [asdict(value) for value in missing], ensure_ascii=False, separators=(",", ":")
        ),
        "critical_value_unsupported": json.dumps(
            [asdict(value) for value in unsupported], ensure_ascii=False, separators=(",", ":")
        ),
    }


def _basic_pair_metrics(original: str, rewritten: str) -> dict[str, float | bool]:
    original_words = set(WORD_PATTERN.findall(original.lower()))
    rewritten_words = set(WORD_PATTERN.findall(rewritten.lower()))
    combined = original_words | rewritten_words
    return {
        "word_overlap": round(len(original_words & rewritten_words) / len(combined), 4)
        if combined else 1.0,
        "edit_ratio": round(1 - SequenceMatcher(None, original, rewritten).ratio(), 4),
        "length_ratio": round(len(rewritten) / len(original), 4) if original else 1.0,
        "exact_match": original.strip() == rewritten.strip(),
    }


def _number_recall(original: str, rewritten: str) -> float:
    # Keep the legacy metric: count numeric surfaces even when nested inside a
    # time, amount, percentage, or measurement.
    source = Counter(_decimal_string(match.group()) for match in NUMBER_PATTERN.finditer(original))
    output = Counter(_decimal_string(match.group()) for match in NUMBER_PATTERN.finditer(rewritten))
    count = sum(source.values())
    preserved = sum(min(amount, output[value]) for value, amount in source.items())
    return round(preserved / count if count else 1.0, 4)


def _toxicity_fields(original: float, rewritten: float) -> dict[str, float]:
    if not (math.isfinite(original) and math.isfinite(rewritten)):
        raise ValueError("toxicity scores must be finite")
    reduction = original - rewritten
    return {
        "toxicity_original": round(float(original), 6),
        "toxicity_rewritten": round(float(rewritten), 6),
        "toxicity_reduction": round(float(reduction), 6),
        "toxicity_relative_reduction": round(float(reduction / max(original, 1e-12)), 6),
    }


def evaluate_pair(
    original: str,
    rewritten: str,
    *,
    annotated_critical_values: str | Sequence[str | Mapping[str, Any]] | None = None,
    toxicity_scorer: ToxicityScorer | None = None,
    similarity_scorer: SimilarityScorer | None = None,
) -> dict[str, float | int | bool | str]:
    """Evaluate one pair. Use ``evaluate_records`` for efficient model batching."""

    result: dict[str, float | int | bool | str] = {
        **critical_value_metrics(original, rewritten, annotated_critical_values),
        **_basic_pair_metrics(original, rewritten),
        "number_recall": _number_recall(original, rewritten),
    }
    if toxicity_scorer is not None:
        scores = toxicity_scorer.score([original, rewritten])
        if len(scores) != 2:
            raise ValueError("toxicity scorer returned the wrong number of scores")
        result.update(_toxicity_fields(scores[0], scores[1]))
    if similarity_scorer is not None:
        scores = similarity_scorer.score_pairs([(original, rewritten)])
        if len(scores) != 1 or not math.isfinite(float(scores[0])):
            raise ValueError("similarity scorer returned invalid scores")
        result["semantic_similarity"] = round(float(scores[0]), 6)
    return result


def evaluate_records(
    records: Sequence[Mapping[str, Any]],
    *,
    toxicity_scorer: ToxicityScorer | None = None,
    similarity_scorer: SimilarityScorer | None = None,
) -> list[dict[str, float | int | bool | str]]:
    """Evaluate records, batching calls to each optional external model."""

    pairs = [(str(row["original_text"]), str(row["rewritten_text"])) for row in records]
    results = [
        evaluate_pair(left, right, annotated_critical_values=row.get("critical_values"))
        for row, (left, right) in zip(records, pairs, strict=True)
    ]
    if toxicity_scorer is not None:
        flattened = [text for pair in pairs for text in pair]
        scores = toxicity_scorer.score(flattened)
        if len(scores) != len(flattened):
            raise ValueError("toxicity scorer returned the wrong number of scores")
        for index, result in enumerate(results):
            result.update(_toxicity_fields(float(scores[index * 2]), float(scores[index * 2 + 1])))
    if similarity_scorer is not None:
        scores = similarity_scorer.score_pairs(pairs)
        if len(scores) != len(pairs):
            raise ValueError("similarity scorer returned the wrong number of scores")
        for result, score in zip(results, scores, strict=True):
            if not math.isfinite(float(score)):
                raise ValueError("semantic similarity scores must be finite")
            result["semantic_similarity"] = round(float(score), 6)
    return results


def summarize(results: Sequence[Mapping[str, Any]]) -> dict[str, float | int | None]:
    summary: dict[str, float | int | None] = {
        "examples": len(results),
        "average_number_recall": _average(results, "number_recall"),
        "average_word_overlap": _average(results, "word_overlap"),
        "average_edit_ratio": _average(results, "edit_ratio"),
        "average_length_ratio": _average(results, "length_ratio"),
        "exact_match_rate": _rate(results, "exact_match"),
    }
    if results and all("critical_value_count" in row for row in results):
        summary.update(
            {
                "critical_value_micro_recall": _weighted_recall(results),
                "critical_value_exact_rate": _rate(results, "critical_value_exact"),
                "total_missing_critical_values": _sum(results, "critical_value_missing_count"),
                "total_unsupported_critical_values": _sum(
                    results, "critical_value_unsupported_count"
                ),
            }
        )
    for output, field in {
        "average_toxicity_original": "toxicity_original",
        "average_toxicity_rewritten": "toxicity_rewritten",
        "average_toxicity_reduction": "toxicity_reduction",
        "average_toxicity_relative_reduction": "toxicity_relative_reduction",
        "average_semantic_similarity": "semantic_similarity",
    }.items():
        if results and all(field in row for row in results):
            summary[output] = _average(results, field)
    return summary


def _rate(records: Sequence[Mapping[str, Any]], field: str) -> float | None:
    return round(sum(bool(row[field]) for row in records) / len(records), 4) if records else None


def _average(records: Sequence[Mapping[str, Any]], field: str) -> float | None:
    return round(sum(float(row[field]) for row in records) / len(records), 4) if records else None


def _sum(records: Sequence[Mapping[str, Any]], field: str) -> int:
    return sum(int(row[field]) for row in records)


def _weighted_recall(records: Sequence[Mapping[str, Any]]) -> float | None:
    total = _sum(records, "critical_value_count")
    if not total:
        return 1.0 if records else None
    return round(_sum(records, "critical_value_preserved_count") / total, 4)
