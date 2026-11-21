"""Dispatch to interchangeable editable, OCR-assisted, and visual Word engines."""

from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Callable
import os
from pathlib import Path
import resource
import shutil
from statistics import mean, median
import subprocess
import sys
import time

import pymupdf

from .layout import _infer_role, assign_running_text, enclosing, extract_layout, overlap, running_text
from .layout_types import Line, PageLayout, Paragraph, Picture, Rect, Table
from .ocr import check_ocr_languages, ocr_page, raster_page
from .pdf_source import EngineError, PageFacts, open_pdf, page_facts, select_pages
from .process_env import processor_environment
from .quality import validate_render, verify_docx
from .word import WordWriter

Progress = Callable[[int], None]
MAX_WARNINGS = 35


class BaseConversionEngine(ABC):
    """Engine contract for source validation, reconstruction, and output checks."""

    def __init__(self, settings: dict, progress: Progress, work_dir: Path) -> None:
        self.settings = settings
        self.progress = progress
        self.work_dir = work_dir
        self.warnings: list[str] = []
        self.page_metrics: list[dict] = []
        self.ocr_pages = 0
        self.ocr_seconds = 0.0

    @staticmethod
    def validate_input(source: Path, max_pages: int, password: str | None) -> pymupdf.Document:
        return open_pdf(source, max_pages=max_pages, password=password)

    def _warnings(self, messages: list[str]) -> None:
        for message in messages:
            if len(self.warnings) < MAX_WARNINGS and message not in self.warnings:
                self.warnings.append(message)

    @abstractmethod
    def reconstruct(self, page: pymupdf.Page, facts: PageFacts | None) -> PageLayout:
        """Recover the content that should appear on this page."""

    def validate_output(
        self, output: Path, document: pymupdf.Document, selected: list[int], writer: WordWriter
    ) -> dict:
        metrics = verify_docx(output, writer.image_count)
        self.progress(90)
        if self.settings.get("validate_render", True):
            rendered, warnings = validate_render(output, document, selected, writer.mode)
            metrics.update(rendered)
            self._warnings(warnings)
        else:
            metrics["render_validated"] = False
        return metrics

    def convert(
        self, document: pymupdf.Document, selected: list[int], facts: dict[int, PageFacts], output: Path
    ) -> dict:
        generation_started = time.monotonic()
        writer = WordWriter(self.settings, selected)
        header_keys, footer_keys = set(), set()
        use_running_text = writer.mode != "visual" and self.settings.get("preserve_headers_footers", True)
        if use_running_text:
            header_keys, footer_keys = running_text(document, selected)
        for offset, index in enumerate(selected):
            page = document[index]
            layout = self.reconstruct(page, facts.get(index))
            if use_running_text:
                assign_running_text(layout, header_keys, footer_keys)
            if not layout.contents and not layout.headers and not layout.footers:
                layout.warnings.append(f"Page {index + 1}: no content could be reconstructed.")
            if layout.source_rotation and writer.mode != "visual":
                layout.warnings.append(f"Page {index + 1}: rotated content was reflowed for Word editing.")
            writer.write_page(layout)
            self._warnings(layout.warnings)
            self.page_metrics.append(
                {
                    "page": layout.number,
                    "classification": layout.kind,
                    "ocr_confidence": layout.ocr_confidence,
                }
            )
            self.progress(18 + round(64 * (offset + 1) / len(selected)))
        writer.save(output)
        docx_seconds = time.monotonic() - generation_started - self.ocr_seconds
        self._warnings(writer.warnings)
        metrics = self.validate_output(output, document, selected, writer)
        scores = [page["ocr_confidence"] for page in self.page_metrics if page["ocr_confidence"] is not None]
        return {
            **metrics,
            "engine": type(self).__name__,
            "phase_seconds": {"docx_seconds": round(max(0., docx_seconds), 4),
                              "ocr_seconds": round(self.ocr_seconds, 4)},
            "selected_pages": len(selected),
            "page_metrics": self.page_metrics,
            "native_content_tables": writer.table_count,
            "page_classification": dict(Counter(page["classification"] for page in self.page_metrics)),
            "ocr_used": bool(self.ocr_pages),
            "ocr_pages": self.ocr_pages,
            "ocr_confidence": round(mean(scores), 1) if scores else None,
            "warnings": self.warnings,
        }


class NativePDFConversionEngine(BaseConversionEngine):
    """Reconstruct editable Word elements using PDF object geometry."""

    def reconstruct(self, page: pymupdf.Page, facts: PageFacts | None) -> PageLayout:
        facts = facts or page_facts(page)
        layout = extract_layout(page, facts, self.settings, ocr=False)
        if facts.needs_ocr:
            layout.warnings.append(f"Page {layout.number}: selective OCR is off, so scanned text may remain an image.")
        return layout


class ScannedPDFConversionEngine(NativePDFConversionEngine):
    """Recover text from scanned pages while keeping reliable native pages editable."""

    def __init__(self, settings: dict, progress: Progress, work_dir: Path) -> None:
        super().__init__(settings, progress, work_dir)
        self.languages = settings.get("languages") or ["eng"]
        self.available = check_ocr_languages(self.languages)

    def reconstruct(self, page: pymupdf.Page, facts: PageFacts | None) -> PageLayout:
        facts = facts or page_facts(page)
        force = self.settings.get("ocr", "auto") == "force"
        if not force and not facts.needs_ocr:
            return super().reconstruct(page, facts)
        layout = extract_layout(page, facts, self.settings, ocr=True)
        self.ocr_pages += 1
        ocr_started = time.monotonic()
        recognized = ocr_page(
            page,
            self.languages,
            detect_rotation="osd" in self.available,
            preserve_tables=facts.needs_ocr and self.settings.get("preserve_tables", True),
            work_dir=self.work_dir,
        )
        self.ocr_seconds += time.monotonic() - ocr_started
        layout.ocr_confidence = recognized.confidence
        if not recognized.paragraphs:
            layout.warnings.append(f"Page {layout.number}: OCR did not recognize any text.")
            if self.settings.get("preserve_images", True) and not layout.contents:
                image = raster_page(page, 150)
                layout.contents.append(Picture(Rect(0, 0, layout.width, layout.height), image.tobytes("png")))
            return layout
        if recognized.confidence is not None and recognized.confidence < 72:
            layout.warnings.append(f"Page {layout.number}: OCR confidence is low. Check spelling and numbers.")
        if recognized.used_sparse_segmentation:
            layout.warnings.append(f"Page {layout.number}: OCR used sparse-text detection. Review the page for missed lines.")
        if recognized.rotation:
            layout.warnings.append(f"Page {layout.number}: OCR corrected a {recognized.rotation}° scan rotation.")
            layout.width, layout.height = recognized.width, recognized.height
            layout.contents = []
        if force:
            layout.contents = [item for item in layout.contents if not isinstance(item, Paragraph)]

        native = [item for item in layout.contents if isinstance(item, Paragraph)]
        body_size = median([span.size for item in recognized.paragraphs for line in item.lines for span in line.spans])
        established = [
            line.box for item in layout.contents if isinstance(item, Paragraph) for line in item.lines
        ]
        tables = [item.box for item in layout.contents if isinstance(item, Table)]
        for table in recognized.tables:
            if all(overlap(table.box, box) < 0.5 for box in tables):
                layout.contents.append(table)
                tables.append(table.box)
        for item in recognized.paragraphs:
            lines = []
            for line in item.lines:
                if any(overlap(line.box, box) >= 0.61 for box in established):
                    continue
                spans = [span for span in line.spans if all(overlap(span.box, box) < 0.61 for box in tables)]
                if spans:
                    lines.append(Line(enclosing(spans), spans))
            if lines:
                item = Paragraph(enclosing(lines), lines)
                _infer_role(item, layout.body_size if native else body_size)
                layout.contents.append(item)
        if not native:
            layout.body_size = body_size
        return layout


class VisualPDFConversionEngine(BaseConversionEngine):
    """Use one full-page picture per selected source page."""

    def reconstruct(self, page: pymupdf.Page, facts: PageFacts | None) -> PageLayout:
        pixmap = raster_page(page, 175)
        layout = PageLayout(page.number + 1, page.rect.width, page.rect.height, "rasterized")
        layout.contents.append(Picture(page.rect, pixmap.tobytes("jpeg", jpg_quality=94), f"Source PDF page {page.number + 1}"))
        return layout


def _qpdf_check(source: Path, encrypted: bool) -> list[str]:
    executable = shutil.which("qpdf")
    if encrypted or not executable or os.environ.get("PDFPRO_QPDF_CHECK") == "0":
        return []
    try:
        result = subprocess.run(
            [executable, "--check", str(source.resolve())], capture_output=True, timeout=30,
            env=processor_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return ["The secondary qpdf structure check could not finish. MuPDF validated the page structure."]
    if result.returncode == 3:
        return ["qpdf reported a recoverable file structure issue. Review the output against the source."]
    if result.returncode:
        raise EngineError("The PDF failed a structural integrity check. Re-export it and try again.")
    return []


def convert_pdf(
    source: Path, output: Path, settings: dict, progress: Progress, *, max_pages: int = 500
) -> dict:
    """Convert a PDF into a real DOCX and report document quality and OCR metrics."""
    mode = settings.get("mode", "editable")
    ocr = settings.get("ocr", "auto")
    if mode not in {"editable", "flowing", "visual"} or ocr not in {"auto", "force", "off"}:
        raise EngineError("Choose a supported conversion mode and OCR policy.")
    started = time.monotonic()
    progress(3)
    try:
        with BaseConversionEngine.validate_input(source, max_pages, settings.get("password")) as document:
            notes = _qpdf_check(source, bool(document.needs_pass))
            selected = select_pages(settings.get("pages"), document.page_count)
            facts: dict[int, PageFacts] = {}
            engine: BaseConversionEngine
            if mode == "visual":
                engine = VisualPDFConversionEngine(settings, progress, output.parent)
                notes.append("Visual layout uses page images. The document text cannot be edited.")
            else:
                progress(9)
                facts = {index: page_facts(document[index]) for index in selected}
                if ocr == "force" or (ocr == "auto" and any(fact.needs_ocr for fact in facts.values())):
                    engine = ScannedPDFConversionEngine(settings, progress, output.parent)
                else:
                    engine = NativePDFConversionEngine(settings, progress, output.parent)
                if document.is_form_pdf:
                    notes.append("Interactive form controls may be omitted from the editable Word document.")
                if document.embfile_count():
                    notes.append("Embedded PDF attachments were omitted.")
            engine._warnings(notes)
            progress(17)
            parsing_seconds = time.monotonic() - started
            metrics = engine.convert(document, selected, facts, output)
            metrics["phase_seconds"]["parse_seconds"] = round(parsing_seconds, 4)
    except EngineError:
        raise
    except (OSError, RuntimeError, ValueError, OverflowError, IndexError) as exc:
        raise EngineError("The PDF contains content that could not be reconstructed into a Word document.") from exc
    metrics["processing_seconds"] = round(time.monotonic() - started, 3)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    metrics["worker_peak_rss_mib"] = round(peak / (1024 ** (2 if sys.platform == "darwin" else 1)), 1)
    progress(97)
    return metrics
