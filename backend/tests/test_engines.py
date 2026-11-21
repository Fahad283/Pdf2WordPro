"""Quality checks using original, generated PDF documents."""

from io import BytesIO
from pathlib import Path
import re
import shutil
from zipfile import ZipFile

from docx import Document
from PIL import Image, ImageDraw
import pymupdf
import pytest

from app.engines import EngineError, convert_pdf, inspect_pdf, open_pdf, select_pages
from app.engines.ocr import check_ocr_languages

LIPSUM = "Editable words follow the original reading order."
SCAN_LINES = [
    "Blue Harbor Certificate",
    "The document was created for testing.",
    "Original sample number 4827",
    "Editable words were recovered from this scan.",
]


def _insert_text(page, point, text, size=11, font="helv", color=(0, 0, 0)):
    page.insert_text(point, text, fontsize=size, fontname=font, color=color)


def _standard_pdf(path: Path, *, count: int = 1) -> Path:
    with pymupdf.open() as pdf:
        for index in range(count):
            page = pdf.new_page()
            _insert_text(page, (50, 90), f"Sample heading {index + 1}", 23, "hebo", (0.2, 0.3, 0.6))
            _insert_text(page, (50, 125), LIPSUM, 11, "tiro")
            _insert_text(page, (50, 145), "Styled information", 11, "hebi", (0.3, 0.1, 0.5))
        pdf.save(path)
    return path


def _artwork() -> bytes:
    image = Image.new("RGB", (240, 110), "#def2fc")
    draw = ImageDraw.Draw(image)
    draw.ellipse((18, 18, 85, 86), fill="#2e64a3")
    draw.rectangle((108, 22, 220, 38), fill="#426887")
    draw.rectangle((108, 51, 168, 72), fill="#7fb1db")
    data = BytesIO()
    image.save(data, format="PNG")
    return data.getvalue()


def _scan_pdf(path: Path, languages: list[str] | None = None, *, mixed: bool = False, rotate: int = 0) -> Path:
    languages = languages or ["eng"]
    with pymupdf.open() as scan, pymupdf.open() as pdf:
        page = scan.new_page(width=520, height=660)
        if languages == ["eng"]:
            for index, line in enumerate(SCAN_LINES):
                _insert_text(page, (70, 150 + index * 31), line, 17 if index else 25, "helv")
            if rotate:
                for index in range(7):
                    _insert_text(page, (70, 295 + index * 27), "A laboratory clerk reviewed the reference.", 17, "helv")
        else:
            phrase = {
                "ara": "هذا مستند عربي لاختبار تحويل النص المكتوب إلى ملف جديد",
                "urd": "یہ اردو دستاویز متن کی شناخت اور تبدیلی کے لیے ہے",
            }[languages[0]]
            page.insert_htmlbox(
                pymupdf.Rect(48, 105, 470, 560),
                f'<div dir="rtl" lang="{languages[0]}">' + f"<p>{phrase}</p>" * 5 + "</div>",
                css="p { font-size: 22pt; line-height: 1.6; }",
            )
        if rotate:
            page.set_rotation(rotate)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2.4, 2.4))
        if mixed:
            digital = pdf.new_page(width=520, height=660)
            _insert_text(digital, (50, 70), "Native digital sample text", 14)
        output = pdf.new_page(width=page.rect.width, height=page.rect.height)
        output.insert_image(output.rect, stream=pixmap.tobytes("png"))
        pdf.save(path)
    return path


def _convert(source: Path, output: Path, **settings) -> dict:
    progress = []
    result = convert_pdf(source, output, {"validate_render": False, **settings}, progress.append)
    assert progress == sorted(progress)
    assert progress[0] == 3 and progress[-1] >= 95
    assert result["docx_valid"]
    assert result["docx_size_bytes"] == output.stat().st_size
    assert result["processing_seconds"] >= 0
    assert result["worker_peak_rss_mib"] > 0
    return result


def _paragraph_text(path: Path) -> str:
    return "\n".join(paragraph.text for paragraph in Document(path).paragraphs)


def _distance(original: list[str], produced: list[str]) -> int:
    previous = list(range(len(produced) + 1))
    for i, source in enumerate(original, start=1):
        current = [i]
        for j, result in enumerate(produced, start=1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (source != result)))
        previous = current
    return previous[-1]


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", text.casefold()))


def test_editable_text_fonts_and_integrity(tmp_path: Path) -> None:
    source = _standard_pdf(tmp_path / "text.pdf")
    output = tmp_path / "text.docx"
    metrics = _convert(source, output, ocr="off")
    assert metrics["engine"] == "NativePDFConversionEngine"
    document = Document(output)
    assert [paragraph.text for paragraph in document.paragraphs] == [
        "Sample heading 1", LIPSUM, "Styled information",
    ]
    assert document.paragraphs[0].style.name == "Heading 1"
    heading = document.paragraphs[0].runs[0]
    assert heading.bold and heading.font.size.pt == 23
    assert all(abs(actual - expected) <= 1 for actual, expected in zip(heading.font.color.rgb, (51, 77, 153)))
    body = document.paragraphs[1].runs[0]
    assert body.font.name in {"Times New Roman", "Times-Roman"}
    assert document.paragraphs[2].runs[0].italic
    with ZipFile(output) as package:
        assert package.testzip() is None
        assert b"Editable words" in package.read("word/document.xml")


def test_multicolumn_reading_order_and_modes(tmp_path: Path) -> None:
    pdf = pymupdf.open()
    page = pdf.new_page(width=605, height=790)
    for x, y, letter in [(340, 190, "RIGHT SECOND"), (52, 135, "LEFT FIRST"), (340, 135, "RIGHT FIRST"), (52, 190, "LEFT SECOND")]:
        _insert_text(page, (x, y), f"{letter} Academic paragraph with several words", 10)
    source = tmp_path / "columns.pdf"
    pdf.save(source); pdf.close()
    flow = tmp_path / "flow.docx"
    layout = tmp_path / "layout.docx"
    visual = tmp_path / "visual.docx"
    _convert(source, flow, mode="flowing", ocr="off")
    _convert(source, layout, mode="editable", ocr="off")
    result = _convert(source, visual, mode="visual")
    flow_text = _paragraph_text(flow)
    assert flow_text.index("LEFT FIRST") < flow_text.index("LEFT SECOND") < flow_text.index("RIGHT FIRST")
    table = Document(layout).tables[0]
    assert "LEFT SECOND" in table.cell(0, 0).text
    assert "RIGHT FIRST" in table.cell(0, 1).text
    assert result["embedded_images"] == 1 and "LEFT FIRST" not in _paragraph_text(visual)


def test_invoice_table_image_annotation_and_hyperlink(tmp_path: Path) -> None:
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=612, height=720)
        _insert_text(page, (54, 55), "Blue Harbor invoice", 21, "hebo")
        page.insert_image((400, 31, 560, 104), stream=_artwork())
        _insert_text(page, (54, 125), "Payment terms")
        link_area = page.search_for("Payment terms")[0]
        page.insert_link({"kind": pymupdf.LINK_URI, "from": link_area, "uri": "https://example.org/payment"})
        page.add_text_annot((560, 125), "Sample annotation")
        for x in [52, 270, 420, 558]:
            page.draw_line((x, 155), (x, 255))
        for y in [155, 180, 205, 230, 255]:
            page.draw_line((52, y), (558, y))
        rows = [["Description", "Qty", "Total"], ["Design", "2", "120.00"], ["Review", "1", "50.00"], ["Sum", "3", "170.00"]]
        for index, row in enumerate(rows):
            for x, text in zip([58, 276, 428], row):
                _insert_text(page, (x, 171 + 25 * index), text)
        source = tmp_path / "invoice.pdf"
        pdf.save(source)
    inspection = inspect_pdf(source)
    assert "table-heavy" in inspection["traits"]
    assert inspection["pages"][0]["hyperlinks"] == inspection["pages"][0]["annotations"] == 1
    target = tmp_path / "invoice.docx"
    result = _convert(source, target, ocr="off")
    document = Document(target)
    assert result["native_content_tables"] == 1
    assert result["embedded_images"] == 1
    grid = next(table for table in document.tables if len(table.rows) == len(rows))
    assert [[cell.text for cell in row.cells] for row in grid.rows] == rows
    assert "Design" not in _paragraph_text(target)
    with ZipFile(target) as package:
        assert b"https://example.org/payment" in package.read("word/_rels/document.xml.rels")


def test_header_footer_list_and_page_selection(tmp_path: Path) -> None:
    with pymupdf.open() as pdf:
        for index in range(3):
            page = pdf.new_page(width=612, height=740)
            _insert_text(page, (62, 32), "Monthly laboratory notes", size=11)
            _insert_text(page, (56, 110), f"Heading for sample {index + 1}", 22, "hebo")
            _insert_text(page, (62, 150), f"Native list for sample {index + 1}")
            _insert_text(page, (75, 185), "3. Check equipment")
            _insert_text(page, (75, 208), "4. Record results")
            _insert_text(page, (282, 710), f"Page {index + 1}")
        source = tmp_path / "notes.pdf"
        pdf.save(source)
    output = tmp_path / "notes.docx"
    _convert(source, output, pages="1,3", ocr="off")
    document = Document(output)
    assert "Heading for sample 2" not in _paragraph_text(output)
    assert document.sections[0].header.paragraphs[0].text == "Monthly laboratory notes"
    assert "Monthly laboratory notes" not in _paragraph_text(output)
    assert "Check equipment" in _paragraph_text(output) and "3. Check equipment" not in _paragraph_text(output)
    with ZipFile(output) as package:
        assert b"PAGE" in package.read("word/footer1.xml")
        assert b"startOverride" in package.read("word/numbering.xml")


def test_image_heavy_report_and_rotation(tmp_path: Path) -> None:
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=610, height=790)
        _insert_text(page, (55, 75), "Illustrated quarterly report", 20, "hebo")
        _insert_text(page, (55, 105), "Ten original illustrations accompany this explanatory project summary.")
        image = _artwork()
        for row in range(5):
            for column in range(2):
                x, y = 58 + column * 255, 130 + row * 110
                page.insert_image((x, y, x + 220, y + 97), stream=image)
        page.set_rotation(90)
        source = tmp_path / "report.pdf"
        pdf.save(source)
    data = inspect_pdf(source)
    assert data["pages"][0]["rotation"] == 90
    assert "image-heavy" in data["traits"]
    output = tmp_path / "report.docx"
    metrics = _convert(source, output, mode="visual")
    assert metrics["embedded_images"] == 1
    section = Document(output).sections[0]
    assert section.page_width.pt == 790
    assert section.page_height.pt == 610


def test_invalid_protected_and_page_limit(tmp_path: Path) -> None:
    forged = tmp_path / "bad.pdf"
    forged.write_bytes(b"%PDF-1.7\nwrong")
    with pytest.raises(EngineError, match="corrupted|damaged"):
        inspect_pdf(forged)
    forged.write_bytes(b"not pdf")
    with pytest.raises(EngineError, match="signature"):
        inspect_pdf(forged)
    source = _standard_pdf(tmp_path / "plain.pdf", count=3)
    with pytest.raises(EngineError, match="2-page processing limit"):
        inspect_pdf(source, max_pages=2)
    secret = tmp_path / "protected.pdf"
    with pymupdf.open(source) as pdf:
        pdf.save(secret, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="testing", owner_pw="sample-owner")
    with pytest.raises(EngineError, match="password-protected"):
        inspect_pdf(secret)
    with pytest.raises(EngineError, match="incorrect"):
        inspect_pdf(secret, password="incorrect")
    with open_pdf(secret, password="testing") as pdf:
        assert len(pdf) == 3
    assert select_pages("3,1-2,2", 3) == [0, 1, 2]
    for selection in ["0", "4", "3-1", "1,,2", "1-2-3", " , "]:
        with pytest.raises(EngineError):
            select_pages(selection, 3)


def test_large_document_and_unusual_fonts(tmp_path: Path) -> None:
    with pymupdf.open() as pdf:
        for index in range(90):
            page = pdf.new_page()
            _insert_text(page, (55, 72), f"Page contents {index + 1}: Standard fallback sample", 11, "cour")
        source = tmp_path / "long.pdf"
        pdf.save(source)
    assert inspect_pdf(source)["page_count"] == 90
    target = tmp_path / "long.docx"
    result = _convert(source, target, ocr="off")
    assert result["selected_pages"] == 90
    assert len(Document(target).paragraphs) >= 90
    assert Document(target).paragraphs[0].runs[0].font.name == "Courier New"


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract is not installed")
def test_mixed_scan_and_ocr_accuracy(tmp_path: Path) -> None:
    source = _scan_pdf(tmp_path / "mixed.pdf", mixed=True)
    inspection = inspect_pdf(source)
    assert inspection["classification"] == "mixed"
    assert [page["ocr_recommended"] for page in inspection["pages"]] == [False, True]
    output = tmp_path / "mixed.docx"
    metrics = _convert(source, output, ocr="auto", languages=["eng"])
    assert metrics["ocr_used"] and metrics["ocr_pages"] == 1
    assert metrics["ocr_confidence"] >= 65
    assert metrics["engine"] == "ScannedPDFConversionEngine"
    recovered = _normalized(_paragraph_text(output)).removeprefix("native digital sample text ").strip()
    original = _normalized(" ".join(SCAN_LINES))
    assert _distance(list(original), list(recovered)) / len(original) <= 0.07
    assert _distance(original.split(), recovered.split()) / len(original.split()) <= 0.12
    assert not list(tmp_path.glob("page-ocr-*"))
    off = tmp_path / "off.docx"
    off_metrics = _convert(source, off, ocr="off")
    assert off_metrics["embedded_images"] == 1
    assert "Blue Harbor" not in _paragraph_text(off)


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract is not installed")
def test_ocr_corrects_a_quarter_turn_scan(tmp_path: Path) -> None:
    if "osd" not in check_ocr_languages(["eng"]):
        pytest.skip("Tesseract orientation data is unavailable")
    source = _scan_pdf(tmp_path / "turned.pdf", rotate=90)
    target = tmp_path / "turned.docx"
    result = _convert(source, target, ocr="auto", languages=["eng"])
    assert "Blue Harbor Certificate" in _paragraph_text(target)
    assert any("corrected a 270° scan rotation" in warning for warning in result["warnings"])
    assert Document(target).sections[0].page_width.pt < Document(target).sections[0].page_height.pt


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract is not installed")
def test_ruled_scanned_invoice_produces_editable_cells(tmp_path: Path) -> None:
    with pymupdf.open() as designed, pymupdf.open() as scan:
        page = designed.new_page(width=590, height=690)
        _insert_text(page, (60, 85), "Blue Harbor Purchase Summary", 25, "hebo")
        for x in (52, 218, 383, 542):
            page.draw_line((x, 155), (x, 387), width=1.4)
        for y in (155, 213, 271, 329, 387):
            page.draw_line((52, y), (542, y), width=1.4)
        rows = [
            ("Product", "Quantity", "Balance"),
            ("Design", "120", "3250"),
            ("Review", "150", "4120"),
            ("Printing", "168", "5655"),
        ]
        for index, row in enumerate(rows):
            for x, label in zip((65, 230, 396), row):
                _insert_text(page, (x, 189 + 58 * index), label, 17)
        raster = page.get_pixmap(matrix=pymupdf.Matrix(2.8, 2.8))
        flat = scan.new_page(width=page.rect.width, height=page.rect.height)
        flat.insert_image(flat.rect, stream=raster.tobytes("png"))
        source = tmp_path / "scanned-invoice.pdf"
        scan.save(source)
    target = tmp_path / "scanned-invoice.docx"
    result = _convert(source, target, ocr="auto", languages=["eng"])
    assert result["ocr_used"] and result["native_content_tables"] == 1
    table = Document(target).tables[0]
    assert table.cell(1, 0).text == "Design"
    assert table.cell(3, 2).text == "5655"


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract is not installed")
def test_unavailable_language_is_actionable(tmp_path: Path) -> None:
    source = _standard_pdf(tmp_path / "sample.pdf")
    with pytest.raises(EngineError, match="language data is missing for zzx"):
        _convert(source, tmp_path / "unavailable.docx", ocr="force", languages=["zzx"])


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract is not installed")
@pytest.mark.parametrize("language", ["ara", "urd"])
def test_multilingual_rtl_ocr(tmp_path: Path, language: str) -> None:
    try:
        check_ocr_languages([language])
    except EngineError as exc:
        pytest.skip(str(exc))
    source = _scan_pdf(tmp_path / f"{language}.pdf", [language])
    output = tmp_path / f"{language}.docx"
    metrics = _convert(source, output, ocr="auto", languages=[language])
    assert metrics["ocr_used"] and metrics["ocr_confidence"] is not None
    text = _paragraph_text(output)
    assert len(re.findall("[\u0600-\u06ff]", text)) >= 25
    if language == "ara":
        assert sum(word in text for word in ("مستند", "عربي", "تحويل")) >= 2
    with ZipFile(output) as package:
        body = package.read("word/document.xml")
        assert b"w:bidi" in body and b"w:rtl" in body


@pytest.mark.skipif(not (shutil.which("soffice") or shutil.which("libreoffice")), reason="LibreOffice unavailable")
def test_word_render_and_visual_similarity(tmp_path: Path) -> None:
    source = _standard_pdf(tmp_path / "source.pdf", count=2)
    path = tmp_path / "visual.docx"
    metrics = _convert(source, path, mode="visual", validate_render=True)
    assert metrics["render_validated"] and metrics["rendered_pages"] == 2
    assert metrics["visual_similarity"] >= 0.80
    assert not list(tmp_path.glob("word-render-*"))
