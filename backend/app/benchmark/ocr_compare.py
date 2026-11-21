"""Measure local OCR pipelines on the same synthetic scan corpus."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import os
import shutil
from statistics import mean
import subprocess
from tempfile import TemporaryDirectory
import time
import unicodedata

import pymupdf

from app.engines.ocr import _decode, _recognize, check_ocr_languages, ocr_page, raster_page
from app.engines.pdf_source import EngineError
from app.engines.process_env import processor_environment

from .fixtures import DATASET_VERSION, catalog, generate
from .text_metrics import compare_text, compare_tables, evidence_excerpt

ENGINES = ("tesseract-pipeline", "tesseract-raw", "paddleocr")
MAX_PADDLE_RESULT_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PaddleModels:
    detection: Path | None = None
    recognition: Path | None = None
    languages: tuple[str, ...] = ()


@dataclass(slots=True)
class OCRObservation:
    text: str
    confidence: float | None
    segments: int
    tables: list[list[list[str]]] | None = None
    rotation: int | None = None


class Unavailable(EngineError):
    """An OCR executable, model, or required alphabet is unavailable."""


def _tesseract_languages(languages: list[str]) -> None:
    try:
        check_ocr_languages(languages)
    except EngineError as exc:
        raise Unavailable(str(exc)) from exc


def _tesseract(page, languages: list[str], work: Path, *, raw: bool) -> OCRObservation:
    _tesseract_languages(languages)
    if raw:
        path = work / "input.png"
        image = raster_page(page, 260, grayscale=True)
        image.set_dpi(260, 260)
        image.save(path)
        paragraphs, confidence = _decode(
            _recognize(path, languages, segmentation="3"),
            page.rect.width / image.width, page.rect.height / image.height,
        )
        tables = None
        rotation = None
    else:
        recognized = ocr_page(page, languages, detect_rotation=True, preserve_tables=True, work_dir=work)
        paragraphs = recognized.paragraphs
        confidence = recognized.confidence
        tables = [table.rows for table in recognized.tables]
        rotation = recognized.rotation
    return OCRObservation(
        "\n".join(line.text for paragraph in paragraphs for line in paragraph.lines),
        confidence / 100 if confidence is not None else None,
        sum(len(paragraph.lines) for paragraph in paragraphs),
        tables,
        rotation,
    )


def _paddle_version() -> str | None:
    # Distribution metadata is optional when the executable uses a separate virtual environment.
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("paddleocr")
    except PackageNotFoundError:
        return None


def _paddle_capability(models: PaddleModels, languages: list[str]) -> tuple[str, Path, Path]:
    command = shutil.which("paddleocr")
    if not command:
        raise Unavailable("Install the local PaddleOCR 3.x CLI and provide locally installed model directories.")
    if models.detection is None or models.recognition is None:
        raise Unavailable("Provide local PaddleOCR detection and recognition model directories.")
    detection, recognition = models.detection.resolve(), models.recognition.resolve()
    if not detection.is_dir() or not recognition.is_dir():
        raise Unavailable("The selected local PaddleOCR model directory does not exist.")
    missing_languages = sorted(set(languages) - set(models.languages))
    if missing_languages:
        raise Unavailable(f"The installed PaddleOCR recognition model has no declared coverage for {', '.join(missing_languages)}.")
    return command, detection, recognition


def _read_paddle_result(result: Path) -> OCRObservation:
    if not result.is_file() or result.stat().st_size > MAX_PADDLE_RESULT_BYTES:
        raise EngineError("PaddleOCR produced no usable JSON result.")
    try:
        payload = json.loads(result.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("res"), dict):
            payload = payload["res"]
        words = payload["rec_texts"]
        scores = payload["rec_scores"]
        if not isinstance(words, list) or not isinstance(scores, list) or len(words) != len(scores):
            raise ValueError("Invalid text and score arrays.")
        if any(not isinstance(text, str) for text in words):
            raise ValueError("Unrecognized OCR text result.")
        if any(not isinstance(score, (int, float)) or not 0 <= score <= 1 for score in scores):
            raise ValueError("Unrecognized OCR score result.")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise EngineError("PaddleOCR output did not match the expected 3.x OCR result schema.") from exc
    return OCRObservation("\n".join(words), mean(scores) if scores else None, len(words))


def _paddle(page, languages: list[str], work: Path, models: PaddleModels) -> OCRObservation:
    command, detection, recognition = _paddle_capability(models, languages)
    raster = raster_page(page, 260, grayscale=True)
    raster.set_dpi(260, 260)
    source = work / "page.png"
    raster.save(source)
    output = work / "paddle-results"
    output.mkdir()
    # Local model paths and disabled auxiliary networks keep this adapter independent
    # of hosted inference, remote document URLs, and automatic model downloads.
    environment = processor_environment(work)
    environment["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    environment["OMP_NUM_THREADS"] = "1"
    try:
        subprocess.run(
            [command, "ocr", "-i", str(source),
             "--text_detection_model_dir", str(detection),
             "--text_recognition_model_dir", str(recognition),
             "--use_doc_orientation_classify", "False",
             "--use_doc_unwarping", "False",
             "--use_textline_orientation", "False",
             "--device", "cpu", "--save_path", str(output)],
            cwd=work, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=180, check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise EngineError("Local PaddleOCR exceeded the page time limit.") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EngineError("Local PaddleOCR could not load the selected models or recognize this page.") from exc
    return _read_paddle_result(output / "page_res.json")


def _script_evidence(text: str) -> dict:
    letters = [character for character in text if character.isalpha()]
    arabic = sum(unicodedata.name(character, "").startswith("ARABIC LETTER ") for character in letters)
    latin = sum(unicodedata.name(character, "").startswith("LATIN ") for character in letters)
    return {
        "alphabetic_characters": len(letters),
        "arabic_script_characters": arabic,
        "latin_script_characters": latin,
        "contains_distinctive_urdu_letters": any(character in "ٹڈڑںےگچپژھ" for character in letters),
    }


def _measurement(page, expected: dict, case: dict, engine: str, work: Path, models: PaddleModels) -> dict:
    expected_text = expected.get("body_text", expected["text"])
    languages = expected["languages"]
    row = {
        "case_id": case["id"],
        "source_sha256": case["sha256"],
        "page": page.number + 1,
        "engine": engine,
        "configured_languages": languages,
        "source_script": _script_evidence(expected_text),
    }
    started = time.monotonic()
    try:
        observed = (
            _paddle(page, languages, work, models) if engine == "paddleocr" else
            _tesseract(page, languages, work, raw=engine == "tesseract-raw")
        )
    except Unavailable as exc:
        return {**row, "status": "unavailable", "error": str(exc)}
    except EngineError as exc:
        return {**row, "status": "failed", "error": str(exc)}
    elapsed = time.monotonic() - started
    metrics, evidence = compare_text(expected_text, observed.text)
    table_score, table_details = (
        compare_tables(expected["tables"], observed.tables) if observed.tables is not None else (None, [])
    )
    return {
        **row,
        "status": "measured",
        "seconds": round(elapsed, 6),
        "confidence": observed.confidence,
        "segments": observed.segments,
        "source_segments": len(expected["blocks"]),
        "rotation_correction": observed.rotation,
        "recognized_script": _script_evidence(observed.text),
        "metrics": metrics,
        "table_score": table_score,
        "table_details": table_details,
        "text": evidence_excerpt(evidence),
    }


def _tesseract_version() -> str | None:
    executable = shutil.which("tesseract")
    if not executable:
        return None
    try:
        response = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=10, check=True, env=processor_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return next(iter(response.stdout.splitlines()), None)


def benchmark_ocr(
    case_ids: list[str], engines: tuple[str, ...] = ENGINES[:2], *, paddle: PaddleModels | None = None,
) -> dict:
    """Score OCR observations from identical authored scan pages and transcripts."""
    definitions = {case["id"]: case for case in catalog()}
    if not case_ids:
        case_ids = [case_id for case_id, case in definitions.items() if case["settings"]["ocr"] == "auto"]
    for case_id in case_ids:
        if case_id not in definitions or definitions[case_id]["settings"]["ocr"] != "auto":
            raise ValueError(f"{case_id!r} is not a synthetic OCR case.")
    if not engines or any(engine not in ENGINES for engine in engines):
        raise ValueError("Select a supported local OCR engine.")
    paddle = paddle or PaddleModels()
    rows = []
    with TemporaryDirectory(prefix="pdfbench-ocr-") as directory:
        root = Path(directory)
        for case_id in dict.fromkeys(case_ids):
            path = root / f"{case_id}.pdf"
            case = generate(case_id, path)
            with pymupdf.open(path) as document:
                for page, expected in zip(document, case["ground_truth"]["pages"], strict=True):
                    if not expected["ocr_required"]:
                        continue
                    for engine in dict.fromkeys(engines):
                        with TemporaryDirectory(dir=root) as work:
                            rows.append(_measurement(page, expected, case, engine, Path(work), paddle))
    summary = {}
    for engine in dict.fromkeys(engines):
        matching = [row for row in rows if row["engine"] == engine]
        measured = [row for row in matching if row["status"] == "measured"]
        summary[engine] = {
            "measured_pages": len(measured),
            "unavailable_pages": sum(row["status"] == "unavailable" for row in matching),
            "failed_pages": sum(row["status"] == "failed" for row in matching),
            **{
                f"mean_{metric}": round(mean(scores), 6) if (
                    scores := [row["metrics"][metric] for row in measured if row["metrics"][metric] is not None]
                ) else None for metric in ("cer", "wer", "reading_order_accuracy")
            },
            "mean_seconds": round(mean(row["seconds"] for row in measured), 6) if measured else None,
        }
    return {
        "dataset_version": DATASET_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "rasterization": {"target_dpi": 260, "colorspace": "grayscale"},
        "engine_versions": {
            "tesseract": _tesseract_version() if set(engines) & set(ENGINES[:2]) else None,
            "paddleocr": _paddle_version() if "paddleocr" in engines else None,
        },
        "summary": summary,
        "pages": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", default=[], help="Synthetic case ID, repeatable")
    parser.add_argument("--engine", choices=ENGINES, action="append", help="Repeat for each desired comparison")
    parser.add_argument("--paddle-detector", type=Path, help="Locally installed detector model directory")
    parser.add_argument("--paddle-recognizer", type=Path, help="Locally installed recognition model directory")
    parser.add_argument("--paddle-language", action="append", default=[], help="Model coverage as ISO 639-3 code, repeatable")
    parser.add_argument("--output", type=Path, help="Write the benchmark report to this JSON path")
    args = parser.parse_args()
    models = PaddleModels(args.paddle_detector, args.paddle_recognizer, tuple(args.paddle_language))
    try:
        result = benchmark_ocr(args.case, tuple(args.engine or ENGINES[:2]), paddle=models)
    except ValueError as exc:
        parser.error(str(exc))
    evidence = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(evidence, encoding="utf-8")
        print(json.dumps(result["summary"], indent=2))
    else:
        print(evidence, end="")
    return 0 if any(row["status"] == "measured" for row in result["pages"]) else EX_UNAVAILABLE


EX_UNAVAILABLE = getattr(os, "EX_UNAVAILABLE", 69)

if __name__ == "__main__":
    raise SystemExit(main())
