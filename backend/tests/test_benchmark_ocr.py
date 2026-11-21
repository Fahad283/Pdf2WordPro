"""Contract checks for local OCR comparison and capability reporting."""

import json
import shutil

import pytest

from app.benchmark.ocr_compare import PaddleModels, _paddle_capability, _read_paddle_result, benchmark_ocr, Unavailable


def test_read_documented_paddle_json_shape(tmp_path):
    path = tmp_path / "page_res.json"
    path.write_text(json.dumps({"res": {"rec_texts": ["مستند عربي", "original"], "rec_scores": [.8, .9]}}))
    observed = _read_paddle_result(path)
    assert observed.text == "مستند عربي\noriginal"
    assert observed.confidence == pytest.approx(.85)
    assert observed.segments == 2
    assert observed.tables is None


def test_paddle_reports_required_language_without_running_a_model(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: "/local/paddleocr")
    with pytest.raises(Unavailable, match="declared coverage for urd"):
        _paddle_capability(PaddleModels(tmp_path, tmp_path, ("eng", "ara")), ["eng", "urd"])


def test_unavailable_paddle_is_not_scored(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    report = benchmark_ocr(["PDF-015"], ("paddleocr",))
    assert report["pages"][0]["status"] == "unavailable"
    assert report["summary"]["paddleocr"]["mean_cer"] is None
    assert report["summary"]["paddleocr"]["measured_pages"] == 0


def test_rejecting_a_fixture_without_an_ocr_page():
    with pytest.raises(ValueError, match="not a synthetic OCR case"):
        benchmark_ocr(["PDF-001"])


@pytest.mark.skipif(not shutil.which("tesseract"), reason="requires local Tesseract")
def test_real_tesseract_comparison_uses_shared_english_reference():
    report = benchmark_ocr(["PDF-015"])
    rows = report["pages"]
    assert len(rows) == 2
    assert {row["status"] for row in rows} == {"measured"}
    assert len({row["source_sha256"] for row in rows}) == 1
    assert rows[0]["metrics"]["cer"] < .07
    assert rows[1]["metrics"]["cer"] < .12
    assert rows[0]["configured_languages"] == ["eng"]
