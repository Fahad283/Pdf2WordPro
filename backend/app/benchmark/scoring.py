"""Traceable normalized scores and unweighted diagnostic aggregates."""

import math
from statistics import mean, median

from .configuration import TERMINAL

RECOMMENDATIONS = {
    "text_accuracy": "Inspect missing lines, Unicode mapping, and reconstructed reading order.",
    "layout_preservation": "Review page geometry, column splits, and font substitutions in the differences.",
    "tables_formatting": "Inspect incomplete table cells and numbering, heading, and paragraph styles.",
    "images_graphics": "Compare expected images and graphics with the editable and rendered outputs.",
    "ocr_performance": "Review low-confidence words, scan rotation, and the selected language packs.",
    "docx_compatibility": "Resolve document package errors and validate the output with LibreOffice.",
    "performance": "Profile the measured conversion phases and check the slowest cases.",
    "reliability": "Review unexpected conversion failures, timeouts, and temporary-file cleanup.",
    "security": "Resolve failed defensive checks before releasing converter changes.",
    "language_support": "Review script recovery and Word right-to-left paragraph direction.",
}


def _average(values) -> float | None:
    included = [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(value)]
    return mean(included) if included else None


def _bounded(value: float | bool | None) -> float | None:
    return max(0., min(1., float(value))) if value is not None else None


def categories(metrics: dict, thresholds: dict, behavior: str) -> dict:
    if behavior == "reject":
        return {"reliability": metrics.get("expected_rejection")}
    duration = metrics.get("conversion_seconds")
    return {
        "text_accuracy": metrics.get("text_accuracy"),
        "layout_preservation": _average(metrics.get(key) for key in ("layout_similarity", "page_completeness")),
        "tables_formatting": _average(metrics.get(key) for key in ("tables_score", "formatting_score")),
        "images_graphics": metrics.get("images_score"),
        "ocr_performance": metrics.get("ocr_accuracy"),
        "docx_compatibility": _average(metrics.get(key) for key in ("docx_valid", "render_valid")),
        "performance": min(1., thresholds["target_seconds"] / max(.001, duration)) if duration is not None else None,
        "reliability": metrics.get("reliability"),
        "language_support": metrics.get("language_score"),
    }


def weighted_score(values: dict, weights: dict) -> tuple[float | None, float]:
    available = {key: _bounded(value) for key, value in values.items() if key in weights and value is not None}
    coverage = sum(weights[key] for key in available)
    if not coverage:
        return None, 0.
    return round(100 * sum(value * weights[key] for key, value in available.items()) / coverage, 2), coverage


def case_verdict(metrics: dict, config: dict, behavior: str, critical: list[str]) -> tuple[float | None, bool, list[str], dict]:
    breakdown = categories(metrics, config["thresholds"], behavior)
    score, _ = weighted_score(breakdown, config["weights"])
    misses = []
    if behavior == "reject":
        if metrics.get("expected_rejection") != 1.:
            misses.append("Expected a safe rejection of the input.")
    else:
        measured = ("text_accuracy", "ocr_accuracy", "page_completeness", "tables_score",
                    "images_score", "layout_similarity", "docx_valid", "cleanup_rate")
        for key in measured:
            value = metrics.get(key)
            if key == "text_accuracy" and metrics.get("ocr_accuracy") is not None and metrics.get("digital_accuracy") is None:
                continue
            if key == "text_accuracy" and metrics.get("digital_accuracy") is not None:
                value = metrics["digital_accuracy"]
            target = config["thresholds"][key]
            if value is not None and value < target:
                misses.append(f"{key.replace('_', ' ').capitalize()} {value:.1%} is below {target:.1%}.")
        if metrics.get("docx_valid") is False or metrics.get("docx_valid") == 0:
            if "DOCX package is invalid." not in critical:
                critical.append("DOCX package is invalid.")
        if metrics.get("conversion_seconds", 0) > config["thresholds"]["target_seconds"]:
            misses.append("Conversion exceeded the configured performance target.")
    return score, not misses and not critical, misses, breakdown


def _percentile(values: list[float], factor: float, minimum: int) -> float | None:
    if len(values) < minimum:
        return None
    index = (len(values) - 1) * factor
    floor = math.floor(index)
    fraction = index - floor
    return round(values[floor] + fraction * (values[math.ceil(index)] - values[floor]), 3)


def summarize(results: list, config: dict, security: list[dict], baseline: dict | None = None) -> dict:
    expected = [result for result in results if result.behavior == "convert"]
    converted = sum(result.conversion_ok is True for result in expected)
    finished = [result for result in results if result.status in TERMINAL]
    documents = [result.metrics or {} for result in finished]
    metric_keys = sorted({key for item in documents for key, value in item.items() if isinstance(value, (int, float))})
    metrics = {key: _average(item.get(key) for item in documents) for key in metric_keys}
    category_values = [
        (result.details or {}).get("category_values", {}) for result in finished
    ]
    scores = {key: _average(item.get(key) for item in category_values) for key in config["weights"]}
    scores["security"] = _average([check["passed"] for check in security])
    durations = sorted(result.duration_seconds for result in expected if result.conversion_ok and result.duration_seconds is not None)
    overall, coverage = weighted_score(scores, config["weights"])
    conversion_rate = converted / len(expected) if expected else None
    critical_ids = [result.case_id for result in finished if (result.details or {}).get("critical")]
    reference_metrics = [(result.details or {}).get("reference", {}).get("metrics", {}) for result in finished]
    references = [item for item in reference_metrics if item]
    reference_keys = sorted({key for item in references for key, value in item.items() if isinstance(value, (int, float))})
    recommendations = [message for key, message in RECOMMENDATIONS.items() if scores.get(key) is not None and scores[key] < .95]
    if any(not check["passed"] for check in security) and RECOMMENDATIONS["security"] not in recommendations:
        recommendations.append(RECOMMENDATIONS["security"])
    if baseline and baseline["overall_score"] is not None and overall is not None:
        baseline = {**baseline, "delta": round(overall - baseline["overall_score"], 2)}
    return {
        "overall_score": overall, "coverage_weight": coverage,
        "category_scores": {key: round(100 * _bounded(value), 2) if value is not None else None for key, value in scores.items()},
        "total": len(results), "successful_conversions": converted,
        "failed_conversions": len(expected) - converted, "conversion_success_rate": conversion_rate,
        "passed_cases": sum(result.passed is True for result in finished),
        "failed_cases": sum(result.passed is False for result in finished),
        "failed_ids": [result.case_id for result in finished if result.passed is False],
        "critical_ids": critical_ids, "metrics": metrics,
        "mean_duration_seconds": round(mean(durations), 3) if durations else None,
        "median_seconds": round(median(durations), 3) if durations else None,
        "p95_seconds": _percentile(durations, .95, 20), "p99_seconds": _percentile(durations, .99, 100),
        "latency_samples": len(durations), "security": security, "recommendations": recommendations,
        "passed": (
            not critical_ids and all(check["passed"] for check in security)
            and all(result.passed is True for result in finished) and len(finished) == len(results)
            and (conversion_rate is None or conversion_rate >= config["thresholds"]["conversion_success"])
        ),
        "baseline": baseline, "references_compared": len(references),
        "reference_metrics": {key: _average(item.get(key) for item in references) for key in reference_keys},
    }
