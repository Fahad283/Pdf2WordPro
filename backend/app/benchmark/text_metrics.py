"""Traceable native DOCX text, layout feature, and table comparisons."""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Sequence
import unicodedata
from typing import TypeVar

from .structure import EditableContent

T = TypeVar("T", bound=Hashable)
MAX_COMPARISON_UNITS = 200_000
MAX_EDIT_MASK_BYTES = 64 * 1024 * 1024
MAX_EXCERPT = 32_000


def normalize(text: str) -> str:
    """Normalize canonical Unicode equivalence and whitespace only."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def _trim(left: Sequence[T], right: Sequence[T]) -> tuple[Sequence[T], Sequence[T]]:
    prefix = 0
    extent = min(len(left), len(right))
    while prefix < extent and left[prefix] == right[prefix]:
        prefix += 1
    suffix = 0
    while suffix < extent - prefix and left[len(left) - suffix - 1] == right[len(right) - suffix - 1]:
        suffix += 1
    return left[prefix:len(left) - suffix], right[prefix:len(right) - suffix]


def _trim_masks(pattern: Sequence[T]) -> dict[T, int] | None:
    if len(pattern) > MAX_COMPARISON_UNITS:
        return None
    offsets = {}
    for position, value in enumerate(pattern):
        offsets[value] = position
    if sum(offset // 8 + 1 for offset in offsets.values()) > MAX_EDIT_MASK_BYTES:
        return None
    masks = {value: bytearray(offset // 8 + 1) for value, offset in offsets.items()}
    for position, value in enumerate(pattern):
        masks[value][position // 8] |= 1 << (position % 8)
    return {value: int.from_bytes(mask, "little") for value, mask in masks.items()}


def edit_distance(expected: Sequence[T], actual: Sequence[T]) -> int | None:
    """Exact Myers bit-vector Levenshtein within the configured evaluation budget."""
    expected, actual = _trim(expected, actual)
    if not expected or not actual:
        return max(len(expected), len(actual))
    if max(len(expected), len(actual)) > MAX_COMPARISON_UNITS:
        return None
    pattern, stream = (expected, actual) if len(expected) <= len(actual) else (actual, expected)
    masks = _trim_masks(pattern)
    if masks is None:
        return None
    high = 1 << (len(pattern) - 1)
    positive, negative, score = -1, 0, len(pattern)
    for token in stream:
        matches = masks.get(token, 0)
        horizontal = (((matches & positive) + positive) ^ positive) | matches
        additions = negative | ~(horizontal | positive)
        deletions = positive & horizontal
        score += bool(additions & high) - bool(deletions & high)
        additions = (additions << 1) | 1
        deletions <<= 1
        positive = deletions | ~(matches | additions)
        negative = additions & matches
    return score


def rate(expected: Sequence[T], actual: Sequence[T]) -> float | None:
    if not expected:
        return None
    edits = edit_distance(expected, actual)
    return None if edits is None else round(edits / len(expected), 6)


def _reading_order(expected: list[str], actual: list[str]) -> float | None:
    if not expected:
        return None
    shared = sum((Counter(expected) & Counter(actual)).values())
    if not shared:
        return 0.0
    if expected == actual:
        return 1.0
    if len(actual) > MAX_COMPARISON_UNITS:
        return None
    masks = _trim_masks(expected)
    if masks is None:
        return None
    sequence = 0
    for token in actual:
        candidates = masks.get(token, 0) | sequence
        sequence = candidates & ~(candidates - ((sequence << 1) | 1))
    return round(sequence.bit_count() / shared, 6)


def accuracy(error: float | None) -> float | None:
    return None if error is None else round(max(0.0, 1 - error), 6)


def compare_text(expected: str, actual: str) -> tuple[dict, dict]:
    normalized_expected, normalized_actual = normalize(expected), normalize(actual)
    expected_words, actual_words = normalized_expected.split(), normalized_actual.split()
    missing = Counter(expected_words) - Counter(actual_words)
    added = Counter(actual_words) - Counter(expected_words)
    overlap = len(expected_words) - sum(missing.values())
    cer, wer = rate(normalized_expected, normalized_actual), rate(expected_words, actual_words)
    raw_cer, raw_wer = rate(expected, actual), rate(expected.split(), actual.split())
    metrics = {
        "cer": cer, "wer": wer, "raw_cer": raw_cer, "raw_wer": raw_wer,
        "text_accuracy": accuracy(cer),
        "text_similarity": (
            round(max(0.0, 1 - cer * len(normalized_expected) / max(len(normalized_expected), len(normalized_actual))), 6)
            if cer is not None else None
        ),
        "reading_order_accuracy": _reading_order(expected_words, actual_words),
        "word_recall": round(overlap / len(expected_words), 6) if expected_words else None,
        "word_precision": round(overlap / len(actual_words), 6) if actual_words else None,
        "missing_words": sum(missing.values()),
        "added_words": sum(added.values()),
        "expected_characters": len(normalized_expected),
        "actual_characters": len(normalized_actual),
    }
    raw = {
        "raw_expected": expected, "raw_actual": actual,
        "normalized_expected": normalized_expected, "normalized_actual": normalized_actual,
        "missing_tokens": [{"token": token[:100], "count": count} for token, count in missing.most_common(60)],
        "added_tokens": [{"token": token[:100], "count": count} for token, count in added.most_common(60)],
    }
    return metrics, raw


def evidence_excerpt(raw: dict) -> dict:
    evidence = {}
    for key, value in raw.items():
        if isinstance(value, str):
            evidence[key] = value[:MAX_EXCERPT]
            if len(value) > MAX_EXCERPT:
                evidence["excerpt_truncated"] = True
        else:
            evidence[key] = value
    return evidence


def _table_similarity(expected: list[list[str]], actual: list[list[str]]) -> tuple[float, float, float]:
    rows = max(len(expected), len(actual))
    cols = max(max(map(len, expected), default=0), max(map(len, actual), default=0))
    if not rows or not cols:
        return 0.0, 0.0, 0.0
    expected_cols = max(map(len, expected), default=0)
    actual_cols = max(map(len, actual), default=0)
    geometry = (min(len(expected), len(actual)) / rows + min(expected_cols, actual_cols) / cols) / 2
    expected_cells = {(row, col): normalize(cell) for row, line in enumerate(expected) for col, cell in enumerate(line)}
    actual_cells = {(row, col): normalize(cell) for row, line in enumerate(actual) for col, cell in enumerate(line)}
    populated = {position for position in expected_cells | actual_cells if (
        expected_cells.get(position) or actual_cells.get(position)
    )}
    exact_matches = sum(expected_cells.get(key) == actual_cells.get(key) for key in populated)
    content = exact_matches / len(populated) if populated else 1.0
    return round(.8 * content + .2 * geometry, 6), round(content, 6), round(geometry, 6)


def compare_tables(expected: list[list[list[str]]], actual: list[list[list[str]]]) -> tuple[float | None, list[dict]]:
    if not expected:
        return None, []
    checks = []
    candidates = sorted(
        (score, source, output, content, geometry)
        for source, expected_grid in enumerate(expected)
        for output, actual_grid in enumerate(actual)
        for score, content, geometry in [_table_similarity(expected_grid, actual_grid)]
        if content > 0 or (not any(any(row) for row in expected_grid) and geometry == 1)
    )
    consumed = set()
    matches = {}
    for score, source, output, content, geometry in reversed(candidates):
        if source not in matches and output not in consumed:
            matches[source] = (score, output, content, geometry)
            consumed.add(output)
    for index, expected_grid in enumerate(expected):
        score, output, content, geometry = matches.get(index, (0.0, None, 0.0, 0.0))
        actual_grid = [] if output is None else actual[output]
        cells = []
        for row, expected_cells in enumerate(expected_grid):
            for column, expected_cell in enumerate(expected_cells):
                current = actual_grid[row][column] if row < len(actual_grid) and column < len(actual_grid[row]) else ""
                if normalize(expected_cell) != normalize(current) and len(cells) < 80:
                    cells.append({
                        "row": row + 1, "column": column + 1,
                        "expected": expected_cell[:250], "actual": current[:250],
                    })
        checks.append({
            "expected_table": index + 1, "actual_table": None if output is None else output + 1,
            "score": score, "content": content, "geometry": geometry, "changed_cells": cells,
        })
    return round(sum(item["score"] for item in checks) / len(checks), 6), checks


def _script_counts(text: str) -> dict[str, int]:
    result = Counter()
    for character in text:
        if not character.isalpha():
            continue
        name = unicodedata.name(character, "")
        if name.startswith("ARABIC"):
            result["Arabic"] += 1
        elif name.startswith("LATIN"):
            result["Latin"] += 1
        elif name.startswith("CYRILLIC"):
            result["Cyrillic"] += 1
        else:
            result["Other"] += 1
    return dict(result)


def language_evidence(languages: list[str], expected: str, actual: str, editable: EditableContent) -> tuple[float | None, dict]:
    source_scripts, output_scripts = _script_counts(expected), _script_counts(actual)
    rtl_languages = sorted(set(languages) & {"ara", "urd", "fas", "heb"})
    script_score = (
        sum(min(output_scripts.get(name, 0), count) for name, count in source_scripts.items())
        / sum(source_scripts.values()) if source_scripts else None
    )
    rtl_evidence = bool(editable.counts["rtl"] and editable.counts["rtl_runs"]) if rtl_languages else None
    if script_score is not None and rtl_evidence is not None:
        script_score = .6 * script_score + .4 * rtl_evidence
    return (
        None if script_score is None else round(script_score, 6),
        {
            "expected_languages": languages, "expected_scripts": source_scripts, "observed_scripts": output_scripts,
            "rtl_languages": rtl_languages, "native_rtl": rtl_evidence,
            "rtl_paragraphs": editable.counts["rtl"], "rtl_runs": editable.counts["rtl_runs"],
        },
    )


def feature_evidence(truth: dict, pages: list, editable: EditableContent) -> tuple[float | None, dict]:
    comparisons = {}
    for name, expected in truth.items():
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 1:
            continue
        if name not in {"headings", "lists", "headers", "footers", "hyperlinks", "footnotes", "page_numbers", "rtl"}:
            continue
        actual = editable.counts[name]
        score = min(actual / expected, 1.0)
        if name in {"headers", "footers"}:
            key = "header_text" if name == "headers" else "footer_text"
            story = editable.headers if name == "headers" else editable.footers
            running = {normalize(page.get(key, "")) for page in pages}
            running.discard("")
            if running:
                combined = normalize("\n".join(story))
                score = sum(text in combined for text in running) / len(running)
        if name == "page_numbers":
            score = float(bool(actual))  # One PAGE field may populate all pages in a section.
        comparisons[name] = {"expected": expected, "actual": actual, "score": round(score, 6)}
    overall = sum(item["score"] for item in comparisons.values()) / len(comparisons) if comparisons else None
    return (None if overall is None else round(overall, 6)), comparisons


def paragraph_evidence(pages: list[dict], actual: list[str]) -> float | None:
    expected = [
        normalize(line)
        for page in pages
        for line in page.get("body_text", page.get("text", "")).splitlines()
        if normalize(line)
    ]
    if not expected:
        return None
    output = Counter(normalize(line) for line in actual)
    correct = sum((Counter(expected) & output).values())
    return round(correct / len(expected), 6)
