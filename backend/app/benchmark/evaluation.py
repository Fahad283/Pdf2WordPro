"""Benchmark a DOCX independently against its PDF and authored ground truth."""

from __future__ import annotations

import json
from pathlib import Path
from time import monotonic

import pymupdf

from app.engines import EngineError, open_pdf
from app.engines.pdf_tools import run_tool

from .structure import inspect_docx
from .text_metrics import (
    accuracy, compare_tables, compare_text, evidence_excerpt, feature_evidence,
    language_evidence, normalize, paragraph_evidence, rate,
)
from .visual import PageProfile, compare_visual


def _body(page: dict) -> str:
    return page.get("body_text", page.get("text", ""))


def _ocr_metrics(pages: list[dict], overall_required: bool, output_body: str,
                 diagnostics: list[dict], profiles: list[PageProfile]) -> dict:
    if any("ocr_required" in page for page in pages):
        scan_indexes = [index for index, page in enumerate(pages) if page.get("ocr_required")]
    else:
        scan_indexes = list(range(len(pages))) if overall_required else []
    annotated = [index for index in scan_indexes if _body(pages[index]).strip()]
    if not annotated:
        return {"ocr_cer": None, "ocr_wer": None, "ocr_accuracy": None, "ocr_pages_scored": 0}
    expected = normalize("\n".join(_body(pages[index]) for index in annotated))
    if len(scan_indexes) == len(pages):
        actual = normalize(output_body)
        evidence = "editable_docx"
    elif diagnostics and profiles:
        evidence = "matched_rendered_pages"
        actual_pages = []
        for index in annotated:
            rendered = diagnostics[index]["rendered_page"] if index < len(diagnostics) else None
            expected_page = normalize(_body(pages[index]))
            actual_page = normalize(profiles[rendered - 1].text) if rendered else ""
            # Strip only the authored running strings when they are actual
            # page boundaries. Mixed source body text remains part of truth.
            header = normalize(pages[index].get("header_text", ""))
            footer = normalize(pages[index].get("footer_text", ""))
            if header:
                actual_page = actual_page.removeprefix(header).strip()
            if footer:
                actual_page = actual_page.removesuffix(footer).strip()
            actual_pages.append(actual_page)
            if index < len(diagnostics):
                diagnostics[index]["ocr_cer"] = rate(expected_page, actual_page)
                diagnostics[index]["ocr_wer"] = rate(expected_page.split(), actual_page.split())
        actual = " ".join(actual_pages)
    else:
        return {"ocr_cer": None, "ocr_wer": None, "ocr_accuracy": None, "ocr_pages_scored": 0}
    cer = rate(expected, actual)
    return {
        "ocr_cer": cer, "ocr_wer": rate(expected.split(), actual.split()), "ocr_accuracy": accuracy(cer),
        "ocr_pages_scored": len(annotated), "ocr_text_source": evidence,
    }


def evaluate(
    source: Path, docx_path: Path, ground_truth: dict, output_dir: Path, *, max_visual_pages: int = 8,
) -> dict:
    """Check package, measure semantic content, render once, and save comparison artifacts."""
    started = monotonic()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source, docx_path = source.resolve(), docx_path.resolve()
    metrics = {
        "docx_valid": False, "render_valid": False, "cer": None, "wer": None,
        "raw_cer": None, "raw_wer": None, "text_accuracy": None, "layout_similarity": None,
        "tables_score": None, "formatting_score": None, "images_score": None, "page_completeness": None,
        "ocr_accuracy": None, "language_score": None, "docx_size_bytes": docx_path.stat().st_size
        if docx_path.is_file() else 0,
    }
    warnings: list[str] = []
    critical: list[str] = []
    result: dict = {
        "metrics": metrics, "pages": [], "extracted": {}, "warnings": warnings, "critical": critical,
        "artifacts": {}, "structure": {}, "features": {}, "tables": [], "languages": {},
    }
    try:
        editable = inspect_docx(docx_path)
    except EngineError as exc:
        critical.append(str(exc))
        metrics["evaluation_seconds"] = round(monotonic() - started, 4)
        return result

    metrics["docx_valid"] = True
    result["structure"] = {
        "counts": dict(editable.counts), "direct_fonts": dict(editable.fonts.most_common(60)),
        "direct_font_sizes_pt": dict(editable.sizes.most_common(50)), "sections": editable.sections,
        "links": editable.links, "contains_editable_text": bool(normalize("\n".join(editable.body))),
    }
    pages = ground_truth.get("pages") or []
    visual_profiles = []
    diagnostics = []
    expected_images = sum(len(page.get("images") or []) for page in pages)
    try:
        with open_pdf(source) as original:
            if len(pages) != len(original):
                if pages:
                    warnings.append("The number of ground-truth pages differs from the PDF.")
                else:
                    warnings.append("Text was compared with the PDF text layer because authored ground truth was unavailable.")
                pages = [
                    pages[index] if index < len(pages) else {"text": page.get_text("text")}
                    for index, page in enumerate(original)
                ]
            if not ground_truth.get("pages"):
                expected_images = sum(len(page.get_image_info()) for page in original)
            rendered_path = output_dir / "rendered.pdf"
            run_tool("word-to-pdf", [docx_path], rendered_path, {}, lambda _: None)
            with pymupdf.open(rendered_path) as rendered:
                metrics["render_valid"] = True
                visual, diagnostics, artifacts, visual_profiles = compare_visual(
                    original, rendered, pages, output_dir, max_visual_pages=max(0, min(max_visual_pages, 24)),
                )
            metrics.update(visual)
            result["pages"] = diagnostics
            result["artifacts"] = {"rendered_pdf": rendered_path.name} | artifacts
            if metrics["source_pages"] != metrics["rendered_pages"]:
                warnings.append("Page count changed between the original PDF and the rendered Word document.")
    except (EngineError, OSError, RuntimeError, ValueError):
        warnings.append("The layout comparison could not finish. Check the input and the LibreOffice worker.")
        critical.append("Rendering or page comparison was unavailable.")

    expected_body = "\n".join(_body(page) for page in pages)
    actual_body = "\n".join(editable.body)
    text_metrics, evidence = compare_text(expected_body, actual_body)
    metrics.update(text_metrics)
    evidence.update({
        "raw_expected_all": "\n".join(page.get("text", "") for page in pages),
        "raw_actual_headers": "\n".join(editable.headers),
        "raw_actual_footers": "\n".join(editable.footers),
        "raw_actual_footnotes": "\n".join(editable.notes),
    })
    result["extracted"] = evidence_excerpt(evidence)
    evidence_path = output_dir / "text-evidence.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
    result["artifacts"]["text_evidence"] = evidence_path.name
    if metrics["cer"] is None and normalize(expected_body):
        warnings.append("Text exceeds the exact edit-distance evaluation budget.")
    if normalize(expected_body) and ground_truth.get("editable_expected", True):
        if not normalize(actual_body):
            critical.append("The DOCX contains no editable body text for a text-bearing source.")
        elif metrics["word_recall"] < .5 and (metrics["cer"] or 0) > .35:
            critical.append("More than half of the expected words are absent from the editable DOCX.")

    table_truth = [table for page in pages for table in page.get("tables", [])]
    metrics["tables_score"], result["tables"] = compare_tables(table_truth, editable.tables)
    metrics["formatting_score"], result["features"] = feature_evidence(
        ground_truth.get("features", {}), pages, editable,
    )
    metrics["paragraph_preservation"] = paragraph_evidence(pages, editable.body)
    metrics["language_score"], result["languages"] = language_evidence(
        ground_truth.get("languages", []), expected_body, actual_body, editable,
    )
    metrics.update(_ocr_metrics(pages, bool(ground_truth.get("ocr_required")), actual_body, diagnostics, visual_profiles))
    if expected_images:
        count_score = min(1.0, editable.counts["images"] / expected_images)
        position_score = metrics.get("image_position_score")
        metrics["images_score"] = (
            round(.65 * count_score + .35 * position_score, 6) if position_score is not None else count_score
        )
        metrics["embedded_image_recall"] = count_score
        metrics["expected_images"] = expected_images
    metrics["evaluation_seconds"] = round(monotonic() - started, 4)
    return result
