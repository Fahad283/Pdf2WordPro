"""Validation, safe PDF opening, and page-level inspection."""

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

PDF_SIGNATURE = re.compile(rb"%PDF-[12]\.[0-9]")
PAGE_NUMBER = re.compile(r"[1-9][0-9]{0,5}\Z")
MAX_PAGE_POINTS = 14_400
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)


class EngineError(ValueError):
    """A document-processing error whose message can be shown to a user."""


@dataclass(frozen=True)
class PageFacts:
    kind: str
    text_characters: int
    image_count: int
    image_coverage: float
    reliable_text: bool

    @property
    def needs_ocr(self) -> bool:
        return self.kind in {"scanned", "mixed"}


def open_pdf(
    path: Path, *, max_pages: int = 500, password: str | None = None
) -> pymupdf.Document:
    """Open a bounded, structurally readable PDF. The caller closes the document."""
    try:
        with path.open("rb") as stream:
            if not PDF_SIGNATURE.search(stream.read(1024)):
                raise EngineError("The file does not have a valid PDF signature.")
        document = pymupdf.open(path, filetype="pdf")
    except EngineError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise EngineError("The PDF is corrupted or could not be opened.") from exc

    try:
        if document.needs_pass:
            if not password:
                raise EngineError("This PDF is password-protected. Supply its password or unlock it first.")
            if not document.authenticate(password):
                raise EngineError("The PDF password is incorrect.")
        if document.is_repaired:
            raise EngineError("The PDF structure is damaged. Re-export the document and try again.")
        if document.page_count < 1:
            raise EngineError("The PDF does not contain any pages.")
        if document.page_count > max_pages:
            raise EngineError(f"The PDF exceeds the {max_pages}-page processing limit.")
        for page in document:
            width, height = page.rect.width, page.rect.height
            if not (0 < width <= MAX_PAGE_POINTS and 0 < height <= MAX_PAGE_POINTS):
                raise EngineError("A page has invalid dimensions or exceeds the supported page size.")
    except EngineError:
        document.close()
        raise
    except (RuntimeError, ValueError) as exc:
        document.close()
        raise EngineError("The PDF page structure could not be read.") from exc
    return document


def select_pages(value: str | None, count: int) -> list[int]:
    """Parse one-based page numbers and inclusive ranges, in source order."""
    if not value or value.strip().lower() == "all":
        return list(range(count))
    if len(value) > 4096:
        raise EngineError("The page selection is too long.")
    selected: set[int] = set()
    for segment in value.split(","):
        bounds = [item.strip() for item in segment.split("-")]
        if len(bounds) > 2 or any(not PAGE_NUMBER.fullmatch(item) for item in bounds):
            raise EngineError("Enter page numbers or ranges such as 1-3,5.")
        start, end = int(bounds[0]), int(bounds[-1])
        if start > end or end > count:
            raise EngineError(f"Select pages between 1 and {count} using ascending ranges.")
        selected.update(range(start - 1, end))
    return sorted(selected)


def _has_overlapping_columns(blocks: list, bounds: pymupdf.Rect) -> bool:
    boxes = [pymupdf.Rect(block[:4]) for block in blocks if block[6] == 0 and len(block[4].strip()) > 10]
    for fraction in (0.33, 0.43, 0.50, 0.57, 0.67):
        middle = bounds.x0 + fraction * bounds.width
        left = [box for box in boxes if box.x1 < middle - 4]
        right = [box for box in boxes if box.x0 > middle + 4]
        if len(left) < 2 or len(right) < 2:
            continue
        overlap = min(max(box.y1 for box in left), max(box.y1 for box in right)) - max(
            min(box.y0 for box in left), min(box.y0 for box in right)
        )
        if overlap > 18:
            return True
    return False


def page_facts(page: pymupdf.Page) -> PageFacts:
    text = page.get_text("text")
    visible = [char for char in text if not char.isspace()]
    legible = sum(char.isalnum() for char in visible)
    clean = sum(char == "\ufffd" or ord(char) < 32 or "\ue000" <= char <= "\uf8ff" for char in visible)
    reliable = legible > 0 and clean / max(1, len(visible)) < 0.2
    images = page.get_image_info()
    bounds = page.rect * page.derotation_matrix
    area = max(1, bounds.get_area())
    boxes = [pymupdf.Rect(image["bbox"]) & bounds for image in images]
    # A tiled scan can have more than one image. Bounding intersections prevent
    # most duplicate decorations from being counted twice.
    large_images: list[pymupdf.Rect] = []
    for box in sorted(boxes, key=lambda rect: rect.get_area(), reverse=True):
        if box.is_empty:
            continue
        overlap = sum((box & seen).get_area() for seen in large_images)
        if overlap < box.get_area() * 0.75:
            large_images.append(box)
        if len(large_images) == 64:
            break
    coverage = min(1.0, sum(box.get_area() for box in large_images) / area)
    if not reliable and (coverage > 0.18 or len(visible) > 2):
        kind = "scanned"
    elif coverage > 0.55 and legible < 100 and len(text.splitlines()) < 6:
        kind = "mixed"
    elif reliable:
        kind = "digital"
    elif images:
        kind = "image-heavy"
    else:
        # Text converted to vector outlines can require OCR as well.
        paths = page.get_cdrawings()
        kind = "scanned" if len(paths) >= 8 else "blank"
    return PageFacts(kind, legible, len(images), coverage, reliable)


def inspect_pdf(
    path: Path, *, max_pages: int = 500, password: str | None = None
) -> dict:
    """Return page geometry, processing hints, and unsupported PDF features."""
    with open_pdf(path, max_pages=max_pages, password=password) as document:
        warnings = []
        if document.embfile_count():
            warnings.append("The PDF contains embedded attachments. They are not carried into Word.")
        if document.is_form_pdf:
            warnings.append("Interactive PDF form fields may be rendered without their interactivity.")
        pages = []
        kinds = set()
        for page in document:
            facts = page_facts(page)
            lines = page.get_text("blocks")
            drawings = page.get_cdrawings()
            horizontal = vertical = 0
            for path_dict in drawings:
                for item in path_dict["items"]:
                    if item[0] == "l":
                        horizontal += abs(item[1][1] - item[2][1]) < 1
                        vertical += abs(item[1][0] - item[2][0]) < 1
                    elif item[0] == "re":
                        horizontal += 2
                        vertical += 2
            table_candidate = horizontal >= 3 and vertical >= 3
            complex_layout = facts.reliable_text and (
                len(lines) >= 18 or _has_overlapping_columns(lines, page.rect * page.derotation_matrix)
            )
            traits = []
            if table_candidate:
                traits.append("table-heavy")
            if facts.image_coverage > 0.3 or facts.image_count >= 4:
                traits.append("image-heavy")
            if complex_layout:
                traits.append("complex-layout")
            kinds.add(facts.kind)
            pages.append(
                {
                    "number": page.number + 1,
                    "width": round(page.rect.width, 2),
                    "height": round(page.rect.height, 2),
                    "rotation": page.rotation,
                    "kind": facts.kind,
                    "classification": facts.kind,
                    "traits": traits,
                    "text_characters": facts.text_characters,
                    "image_count": facts.image_count,
                    "image_coverage": round(facts.image_coverage, 3),
                    "ocr_recommended": facts.needs_ocr,
                    "hyperlinks": len(page.get_links()),
                    "annotations": sum(1 for _ in page.annots() or ()),
                }
            )
        if "mixed" in kinds or ("digital" in kinds and "scanned" in kinds):
            document_kind = "mixed"
        elif "scanned" in kinds:
            document_kind = "scanned"
        elif "digital" in kinds:
            document_kind = "digital"
        elif "image-heavy" in kinds:
            document_kind = "image-heavy"
        else:
            document_kind = "blank"
        return {
            "page_count": document.page_count,
            "classification": document_kind,
            "traits": sorted({trait for page_info in pages for trait in page_info["traits"]}),
            "pages": pages,
            "ocr_recommended": any(page["ocr_recommended"] for page in pages),
            "encrypted": bool(document.needs_pass),
            "warnings": warnings,
        }
