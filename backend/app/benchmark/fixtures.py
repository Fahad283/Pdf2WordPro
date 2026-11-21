"""Generate versioned, original PDF fixtures independently of the converter."""

from collections import Counter
from hashlib import sha256
from pathlib import Path
import re

import pymupdf as fitz

from .fixture_catalog import Case, DATASET_VERSION, SCAN_DESIGNS, entries
from .fixture_designs import Sheet, degraded_scan, draw_sheet
from .fixture_integrity import empty_pdf, sign_pdf

_CASES = entries()
_DEFAULT_PAGE = (595, 725)
_SCAN_PAGE = (520, 640)
_VARIABLE_PAGES = ((595, 725), (750, 500), (560, 560))
_SCANNER_LANGUAGES = {"eng", "ara", "urd"}
_SIMPLE_REJECTIONS = {
    "bad-signature": b"Plain text fixture with a deliberately incorrect PDF signature.\n",
    "corrupt": b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R",
    "empty-pdf": empty_pdf(),
}


def _public(case_id: str, case: Case) -> dict:
    scanned = case.design in SCAN_DESIGNS
    languages = [language for language in case.languages if language in _SCANNER_LANGUAGES]
    settings = {"mode": "editable", "ocr": "auto" if scanned else "off", "validate_render": False}
    if languages:
        settings["languages"] = languages
    return {
        "id": case_id,
        "filename": f"{case_id}.pdf",
        "category": case.category,
        "description": case.title,
        "behavior": "reject" if case.rejection else "convert",
        "settings": settings,
        "expected_error": case.rejection,
        "expected_pages": 0 if case.design in _SIMPLE_REJECTIONS else case.pages,
    }


def catalog() -> list[dict]:
    """List the stable case identities and settings without generating any PDFs."""
    return [_public(case_id, case) for case_id, case in _CASES.items()]


def _scan_settings(case: Case, index: int) -> tuple[int | None, float, int]:
    design = case.design
    if design not in SCAN_DESIGNS or (design in {"mixed-scan", "mixed-language-pages"} and index == 0):
        return None, 0, 90 if design == "page-rotation" else 0
    dpi = 230
    if design == "low-scan" or (design == "mixed-language-pages" and case.languages[index] == "eng"):
        dpi = 80
    if design == "mixed-dpi" and index == 1:
        dpi = 88
    skew = {"skew-scan": 3.5, "rtl-skew": 2.6}.get(design, 0)
    rotation = {"rotate-scan": 90, "inverted-scan": 180}.get(design, 0)
    return dpi, skew, rotation


def _size(case: Case, index: int, scanned: bool) -> tuple[int, int]:
    if case.design == "dimension-limit":
        return (20_001, 500)
    if case.design == "varying":
        return _VARIABLE_PAGES[index]
    if case.design in {"wide-grid", "landscape"} or (case.design == "composite" and index == 1):
        return (790, 680) if case.design == "composite" else (790, 520)
    if case.design == "small":
        return (340, 220)
    if case.design == "narrow":
        return (280, 680)
    if case.design == "insets":
        return ((565, 710), (640, 765), (620, 710))[index]
    return _SCAN_PAGE if scanned else _DEFAULT_PAGE


def _render_sheet(case: Case, number: int, index: int, target: fitz.Page) -> tuple[dict, Counter]:
    dpi, skew, rotation = _scan_settings(case, index)
    width, height = target.rect.width, target.rect.height
    if dpi:
        with fitz.open() as master:
            sheet = Sheet(master.new_page(width=width, height=height))
            draw_sheet(sheet, case, number, index, scanned=True)
            scan = degraded_scan(sheet.page, dpi=dpi, skew=skew, degradation=case.design, seed=number * 100 + index)
            target.insert_image(target.rect, stream=scan)
            if case.design == "mixed-layer":
                overlay = Sheet(target)
                overlay.line("Digital reference BH-058", 55, 52, size=12)
                sheet.blocks = overlay.blocks + sheet.blocks
                sheet.fonts.update(overlay.fonts)
    else:
        sheet = Sheet(target)
        draw_sheet(sheet, case, number, index, scanned=False)
    languages = (case.languages[index],) if case.design == "mixed-language-pages" else case.languages
    truth = sheet.truth(languages=languages, ocr_required=bool(dpi), width=width, height=height, rotation=rotation, skew=skew, dpi=dpi)
    target.set_rotation(rotation)
    return truth, sheet.features


def _create(case_id: str, case: Case, destination: Path) -> tuple[list[dict], Counter]:
    if case.design in _SIMPLE_REJECTIONS:
        destination.write_bytes(_SIMPLE_REJECTIONS[case.design])
        return [], Counter()
    number = int(case_id.partition("-")[2])
    pages = []
    features = Counter()
    with fitz.open() as pdf:
        for index in range(case.pages):
            dpi, _, _ = _scan_settings(case, index)
            width, height = _size(case, index, bool(dpi))
            pdf.new_page(width=width, height=height)
        pdf.set_metadata({
            "title": f"{case_id} - {case.title}",
            "author": "PDF2DOCX-BENCH synthetic QA",
            "subject": "Original synthetic benchmark document",
            "creator": DATASET_VERSION,
            "creationDate": "D:20260101000000Z",
            "modDate": "D:20260101000000Z",
        })
        for index in range(case.pages):
            page, page_features = _render_sheet(case, number, index, pdf[index])
            pages.append(page)
            features.update(page_features)
        if case.design == "links":
            pdf.set_toc([[1, f"Record {index + 1}", index + 1] for index in range(case.pages)])
        if case.design == "signed":
            destination.write_bytes(sign_pdf(pdf))
        elif case.design == "bad-xref":
            data = pdf.tobytes(deflate=True, no_new_id=True)
            damaged = re.sub(rb"startxref\s+\d+\s+(?=%%EOF)", b"startxref\n1\n", data)
            destination.write_bytes(damaged)
        elif case.design == "protected":
            pdf.save(
                destination, encryption=fitz.PDF_ENCRYPT_AES_256,
                user_pw="Synthetic-Test-Reader-024", owner_pw="Synthetic-Test-Owner-024",
            )
        else:
            pdf.save(destination, deflate=True, no_new_id=True, garbage=3)
    return pages, features


def generate(case_id: str, destination: Path) -> dict:
    """Materialize one PDF, retaining source expectations and byte integrity."""
    case = _CASES.get(case_id)
    if case is None:
        raise ValueError(f"Unknown synthetic benchmark case {case_id!r}.")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pages, counts = _create(case_id, case, destination)
    with destination.open("rb") as source:
        digest = sha256()
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
    return {
        **_public(case_id, case),
        "dataset_version": DATASET_VERSION,
        "sha256": digest.hexdigest(),
        "size_bytes": destination.stat().st_size,
        "ground_truth": {
            "pages": pages,
            "features": dict(counts),
            "languages": list(case.languages),
            "ocr_required": any(page["ocr_required"] for page in pages),
        },
    }


__all__ = ["DATASET_VERSION", "catalog", "generate"]
