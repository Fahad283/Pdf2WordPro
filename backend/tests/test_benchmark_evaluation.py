from __future__ import annotations

from itertools import product
from pathlib import Path
import shutil
from zipfile import ZipFile

from docx import Document
import numpy as np
from PIL import Image
import pymupdf
import pytest

from app.benchmark.evaluation import evaluate
from app.benchmark.structure import inspect_docx
from app.benchmark.text_metrics import compare_tables, compare_text, edit_distance
from app.benchmark.visual import PageProfile, match_pages, ssim
from app.engines import EngineError, convert_pdf


def _distance_reference(first, second):
    previous = list(range(len(second) + 1))
    for index, left in enumerate(first, 1):
        current = [index]
        for column, right in enumerate(second, 1):
            current.append(min(current[-1] + 1, previous[column] + 1, previous[column - 1] + (left != right)))
        previous = current
    return previous[-1]


def test_exact_edit_metrics_do_not_fold_case_punctuation_or_diacritics():
    small = ["", "a", "ab", "cab", "ttt", "ABCDE", "اُردُو", "عَرَبِيّ"]
    for left, right in product(small, repeat=2):
        assert edit_distance(left, right) == _distance_reference(left, right)
    scores, evidence = compare_text("Café\nalpha beta", "Cafe\u0301 beta alpha")
    assert scores["raw_cer"] != scores["cer"]
    assert scores["cer"] > 0
    assert scores["reading_order_accuracy"] == pytest.approx(2 / 3)
    assert scores["word_recall"] == 1
    assert evidence["raw_expected"] == "Café\nalpha beta"
    assert evidence["normalized_expected"] == "Café alpha beta"
    scores, evidence = compare_text("Résumé: Number ١", "resume number 1")
    assert scores["word_recall"] == 0
    assert scores["wer"] == 1
    assert len(evidence["missing_tokens"]) == 3


def test_table_measure_requires_matching_positions_and_content():
    table = [["Item", "Count"], ["Blue", "11"]]
    score, checks = compare_tables([table], [[["Item", "Count"], ["Blue", "12"]]])
    assert score == .8
    assert checks[0]["changed_cells"] == [{"row": 2, "column": 2, "expected": "11", "actual": "12"}]
    assert compare_tables([table], [[["unrelated cell"]]])[0] == 0
    assert compare_tables([table], [table])[0] == 1


def test_package_reads_real_headings_tables_and_sections(tmp_path):
    source = tmp_path / "real.docx"
    doc = Document()
    doc.add_heading("Independent contents", level=1)
    doc.add_paragraph("An item", style="List Bullet")
    table = doc.add_table(2, 2)
    table.cell(0, 0).text = "Item"
    table.cell(1, 0).text = "Blue"
    doc.sections[0].header.paragraphs[0].text = "Running header"
    doc.save(source)
    inspected = inspect_docx(source)
    assert inspected.counts["headings"] == 1
    assert inspected.counts["lists"] == 1
    assert inspected.counts["native_tables"] == 1
    assert inspected.tables[0][1][0] == "Blue"
    assert inspected.headers == ["Running header"]
    assert inspected.sections[0]["width"] > 0


def test_invalid_relationship_is_rejected_before_rendering(tmp_path):
    original = tmp_path / "good.docx"
    malformed = tmp_path / "malformed.docx"
    doc = Document()
    doc.add_paragraph("Real body")
    doc.save(original)
    with ZipFile(original) as readable, ZipFile(malformed, "w") as output:
        for item in readable.infolist():
            content = readable.read(item)
            if item.filename == "_rels/.rels":
                content = content.replace(b"word/document.xml", b"word/missing.xml")
            output.writestr(item, content)
    with pytest.raises(EngineError, match="missing part"):
        inspect_docx(malformed)
    result = evaluate(tmp_path / "absent.pdf", malformed, {}, tmp_path / "out")
    assert not result["metrics"]["docx_valid"]
    assert not result["artifacts"]
    assert result["critical"]


def test_ssim_and_page_matching_discriminate_changed_pixels_and_insertions():
    original = np.full((80, 100), 255, dtype=np.uint8)
    original[20:30, 10:90] = 16
    shifted = np.roll(original, 10, axis=0)
    assert ssim(original, original) == pytest.approx(1)
    assert ssim(original, shifted) < .9

    from collections import Counter

    def page(text):
        return PageProfile(text, Counter(text.split()), 612, 792)
    aligned, extras = match_pages([page("first"), page("second")], [page("first"), page("extra"), page("second")])
    assert aligned == {0: 0, 1: 2}
    assert extras == [1]


def _fixture(path: Path):
    with pymupdf.open() as document:
        page = document.new_page(width=612, height=792)
        page.insert_text((54, 76), "Independent benchmark heading", fontsize=20)
        page.insert_text((54, 123), "The editable output must preserve this line.", fontsize=12)
        document.save(path)
    return {"pages": [{
        "text": "Independent benchmark heading\nThe editable output must preserve this line.",
        "width": 612, "height": 792, "images": [], "tables": [],
    }], "features": {"headings": 1}, "languages": ["eng"]}


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice worker is required")
def test_live_engine_produces_editable_text_visual_diagnostics_and_complete_page(tmp_path):
    source, word = tmp_path / "source.pdf", tmp_path / "actual.docx"
    truth = _fixture(source)
    convert_pdf(source, word, {"mode": "editable", "ocr": "off", "validate_render": False}, lambda _: None)
    result = evaluate(source, word, truth, tmp_path / "out", max_visual_pages=1)
    assert result["metrics"]["docx_valid"] and result["metrics"]["render_valid"]
    assert result["metrics"]["page_completeness"] == 1
    assert result["metrics"]["cer"] == 0
    assert result["metrics"]["layout_similarity"] > 0
    assert result["metrics"]["ocr_accuracy"] is None
    assert not result["critical"]
    assert result["pages"][0]["rendered_page"] == 1
    assert result["pages"][0]["ssim"] <= 1
    assert {"rendered_pdf", "original_001", "rendered_001", "difference_001", "text_evidence"} <= set(result["artifacts"])
    for filename in result["artifacts"].values():
        assert (tmp_path / "out" / filename).stat().st_size > 0


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice worker is required")
def test_visual_only_docx_is_critical_when_editable_text_is_expected(tmp_path):
    source, word = tmp_path / "source.pdf", tmp_path / "image-only.docx"
    truth = _fixture(source)
    image_path = tmp_path / "image.png"
    Image.new("RGB", (150, 100), "#2951a4").save(image_path)
    output = Document()
    output.add_picture(str(image_path))
    output.save(word)
    result = evaluate(source, word, truth, tmp_path / "out", max_visual_pages=1)
    assert result["metrics"]["docx_valid"]
    assert not result["structure"]["contains_editable_text"]
    assert result["metrics"]["text_accuracy"] == 0
    assert any("no editable body text" in message for message in result["critical"])
