"""Smoke-test each toolkit operation using generated documents."""

from pathlib import Path
from zipfile import ZipFile
import shutil

import pymupdf
import pytest
from docx import Document
from PIL import Image, ImageDraw

from app.engines import EngineError
from app.engines.pdf_tools import TOOL_OUTPUTS, run_tool, validate_docx


@pytest.fixture
def source_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "source.pdf"
    with pymupdf.open() as document:
        for index in range(3):
            page = document.new_page(width=420, height=600)
            page.insert_text((45, 80), f"Original generated page {index + 1}", fontsize=18)
        document.save(path)
    return path


def run(tool, sources, tmp_path, **settings):
    output = tmp_path / f"{tool}{TOOL_OUTPUTS[tool]}"
    updates = []
    result = run_tool(tool, sources, output, settings, updates.append)
    assert output.is_file()
    assert updates == sorted(updates)
    assert updates[0] == 8 and updates[-1] == 95
    return output, result


def test_combine_and_split_pdf(source_pdf, tmp_path):
    merged, metrics = run("merge-pdf", [source_pdf, source_pdf], tmp_path)
    assert metrics["pages"] == 6
    output, metrics = run("split-pdf", [merged], tmp_path, pages="1-2,5", split_mode="ranges")
    assert metrics["parts"] == 2
    with ZipFile(output) as archive:
        first, second = archive.namelist()
        with pymupdf.open(stream=archive.read(first), filetype="pdf") as part:
            assert len(part) == 2
        with pymupdf.open(stream=archive.read(second), filetype="pdf") as part:
            assert len(part) == 1
            assert "page 2" in part[0].get_text()


@pytest.mark.parametrize(
    ("tool", "pages", "first_text", "length"),
    [("extract-pages", "2-3", "page 2", 2), ("delete-pages", "1,3", "page 2", 1)],
)
def test_change_page_selection(tool, pages, first_text, length, source_pdf, tmp_path):
    output, _ = run(tool, [source_pdf], tmp_path, pages=pages)
    with pymupdf.open(output) as document:
        assert len(document) == length
        assert first_text in document[0].get_text()


def test_rotate_and_stamp(source_pdf, tmp_path):
    rotated, _ = run("rotate-pdf", [source_pdf], tmp_path, pages="2", rotation=180)
    with pymupdf.open(rotated) as document:
        assert [page.rotation for page in document] == [0, 180, 0]
    stamped, _ = run("watermark-pdf", [rotated], tmp_path, pages="2", text="Draft <2026>")
    numbered, _ = run("page-numbers", [stamped], tmp_path, pages="2-3", start_number=19)
    with pymupdf.open(numbered) as document:
        assert "Draft <2026>" in document[1].get_text()
        assert "19" in document[1].get_text()
        assert "20" in document[2].get_text()
        assert "Draft" not in document[0].get_text()


@pytest.mark.parametrize("level", ["lossless", "balanced", "strong"])
def test_compress_preserves_selectable_text(source_pdf, tmp_path, level):
    output, metrics = run("compress-pdf", [source_pdf], tmp_path, compression=level)
    assert output.stat().st_size <= source_pdf.stat().st_size
    assert metrics["bytes_saved"] >= 0
    with pymupdf.open(output) as document:
        assert "generated page 1" in document[0].get_text()


def test_pdf_and_jpg_round_trip(source_pdf, tmp_path):
    output, _ = run("pdf-to-jpg", [source_pdf], tmp_path, pages="1,3", dpi=72)
    images = []
    with ZipFile(output) as archive:
        assert archive.namelist() == ["page-001.jpg", "page-003.jpg"]
        for name in archive.namelist():
            file = tmp_path / name
            file.write_bytes(archive.read(name))
            with Image.open(file) as image:
                assert image.size == (420, 600)
            images.append(file)
    _, metrics = run("jpg-to-pdf", images, tmp_path)
    assert metrics["pages"] == 2


@pytest.mark.skipif(not shutil.which("qpdf"), reason="qpdf is not installed")
@pytest.mark.parametrize("password", ["document-fixture-password", "Müller\nfixture-password"])
def test_protect_and_unlock_pdf(source_pdf, tmp_path, password):
    encrypted, _ = run("protect-pdf", [source_pdf], tmp_path, password=password)
    expected = [f"Original generated page {page}" for page in range(1, 4)]
    with pymupdf.open(encrypted) as document:
        assert document.needs_pass
        assert document.authenticate(password)
        assert [page.get_text().strip() for page in document] == expected
    with pytest.raises(EngineError, match="password is incorrect"):
        run("unlock-pdf", [encrypted], tmp_path, password="incorrect")
    output, _ = run("unlock-pdf", [encrypted], tmp_path, password=password)
    with pymupdf.open(output) as document:
        assert not document.needs_pass
        assert [page.get_text().strip() for page in document] == expected


def test_reject_bad_range_and_empty_output(source_pdf, tmp_path):
    with pytest.raises(EngineError, match="range"):
        run("split-pdf", [source_pdf], tmp_path, pages="1,,2", split_mode="ranges")
    with pytest.raises(EngineError, match="at least one"):
        run("delete-pages", [source_pdf], tmp_path, pages="all")


def test_reject_unsafe_docx_archive(tmp_path):
    source = tmp_path / "invalid.docx"
    with ZipFile(source, "w") as package:
        package.writestr("[Content_Types].xml", "")
        package.writestr("word/document.xml", "")
        package.writestr("../unsafe", "invalid")
    with pytest.raises(EngineError, match="unsafe archive"):
        validate_docx(source)


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice is not installed")
def test_word_to_pdf(tmp_path):
    source = tmp_path / "report.docx"
    doc = Document()
    doc.add_paragraph("Editable report rendered by LibreOffice")
    doc.save(source)
    output, _ = run("word-to-pdf", [source], tmp_path)
    with pymupdf.open(output) as document:
        assert "Editable report rendered by LibreOffice" in document[0].get_text()


@pytest.mark.skipif(
    not shutil.which("tesseract") or not shutil.which("ocrmypdf"),
    reason="Tesseract and OCRmyPDF are required",
)
def test_searchable_pdf_with_ocr(tmp_path):
    source = tmp_path / "scan.pdf"
    image = Image.new("RGB", (1000, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 150), "SEARCHABLE DOCUMENT", fill="black", font_size=56)
    raster = tmp_path / "scan.png"
    image.save(raster)
    with pymupdf.open() as document:
        page = document.new_page(width=500, height=200)
        page.insert_image(page.rect, filename=str(raster))
        assert not page.get_text().strip()
        document.save(source)
    output, metrics = run("ocr-pdf", [source], tmp_path, languages=["eng"])
    assert metrics["ocr_pages"] == 1
    with pymupdf.open(output) as document:
        assert "SEARCHABLE DOCUMENT" in document[0].get_text()
