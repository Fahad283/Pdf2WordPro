"""Run a single benchmark in a bounded process without network credentials."""

import json
from pathlib import Path
import resource
import sys
import time

from app.engines import EngineError, convert_pdf


def execute(work: Path, config: dict) -> dict:
    source, produced = work / "source.pdf", work / "produced.docx"
    truth = config["ground_truth"]
    started = time.monotonic()
    is_rejection = config["behavior"] == "reject"
    try:
        conversion = convert_pdf(source, produced, {**config["settings"], "validate_render": False},
                                 lambda _: None, max_pages=config["max_pages"])
    except EngineError as exc:
        reason = str(exc)
        expected = config.get("expected_error")
        gate = is_rejection and (not expected or expected.casefold() in reason.casefold())
        return {
            "conversion_ok": False, "execution_ok": gate, "error": reason,
            "metrics": {"expected_rejection": float(gate)} if is_rejection else {"docx_valid": 0.},
            "critical": [] if gate else ["The converter rejected a supported file." if not is_rejection else
                                         "The rejection reason differs from the expected validation outcome."],
        }
    if is_rejection:
        return {"conversion_ok": True, "execution_ok": False, "error": "The converter accepted a negative fixture.",
                "metrics": {"expected_rejection": 0.}, "critical": ["An invalid input was accepted."]}

    from .evaluation import evaluate

    elapsed = time.monotonic() - started
    output = work / "evaluation"
    output.mkdir()
    try:
        result = evaluate(source, produced, truth, output, max_visual_pages=config["max_visual_pages"])
    except Exception as exc:
        result = {
            "metrics": {}, "critical": ["Quality evaluation failed."],
            "error": f"The evaluator could not process this result ({type(exc).__name__}).",
        }
    result.setdefault("metrics", {}).update({
        "conversion_seconds": round(elapsed, 4), "docx_bytes": produced.stat().st_size,
        "source_bytes": source.stat().st_size, "ocr_confidence": conversion.get("ocr_confidence"),
        "ocr_pages": conversion.get("ocr_pages"), **conversion.get("phase_seconds", {}),
    })
    result["conversion_ok"] = True
    result["execution_ok"] = "error" not in result
    result["engine"] = conversion.get("engine")
    result["conversion"] = conversion
    result["artifacts"] = {
        label: str(Path("evaluation") / filename) for label, filename in result.get("artifacts", {}).items()
    }
    result["artifacts"]["produced_docx"] = produced.name
    reference = work / "reference.docx"
    if reference.exists():
        reference_output = work / "reference-evaluation"
        reference_output.mkdir()
        try:
            comparison = evaluate(source, reference, truth, reference_output,
                                  max_visual_pages=config["max_visual_pages"])
            comparison["artifacts"] = {
                label: str(Path("reference-evaluation") / filename)
                for label, filename in comparison.get("artifacts", {}).items()
            }
            result["reference"] = comparison
        except Exception as exc:
            result["reference"] = {"error": f"Reference evaluation failed ({type(exc).__name__})."}
    return result


def main() -> None:
    work = Path(sys.argv[1]).resolve()
    config = json.loads((work / "config.json").read_text())
    ceiling = config["timeout_seconds"] + 5
    resource.setrlimit(resource.RLIMIT_CPU, (ceiling, ceiling + 2))
    output_limit = 256 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit, output_limit))
    result = execute(work, config)
    own = resource.getrusage(resource.RUSAGE_SELF)
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    scale = 1024 ** (2 if sys.platform == "darwin" else 1)
    result.setdefault("metrics", {}).update({
        "cpu_seconds": round(own.ru_utime + own.ru_stime + child.ru_utime + child.ru_stime, 4),
        "peak_rss_mib": round(max(own.ru_maxrss, child.ru_maxrss) / scale, 2),
    })
    (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
