"""Corpus integrity and authored ground-truth regression checks."""

from collections import Counter
from hashlib import sha256
import re

from cryptography.hazmat.primitives.serialization.pkcs7 import load_der_pkcs7_certificates
from cryptography.x509.oid import NameOID
import pymupdf
import pytest

from app.benchmark.fixtures import DATASET_VERSION, catalog, generate
from app.engines.pdf_source import EngineError, open_pdf


def test_catalog_has_exactly_100_stable_cases() -> None:
    source = catalog()
    assert [case["id"] for case in source] == [f"PDF-{index:03}" for index in range(1, 101)]
    assert len({case["description"] for case in source}) == 100
    categories = Counter(case["category"] for case in source)
    assert set(categories) == {
        "digital", "complex-layout", "tables", "images", "scans", "multilingual", "rtl",
        "technical", "forms", "large", "invalid",
    }
    assert sum(case["expected_pages"] >= 100 and case["behavior"] == "convert" for case in source) >= 3
    assert all(category_count >= 5 for category_count in categories.values())


@pytest.mark.parametrize("definition", catalog(), ids=lambda case: case["id"])
def test_every_fixture_has_verified_bytes_and_matching_expectations(tmp_path, definition) -> None:
    path = tmp_path / definition["filename"]
    metadata = generate(definition["id"], path)
    truth = metadata["ground_truth"]
    assert metadata["dataset_version"] == DATASET_VERSION
    assert metadata["sha256"] == sha256(path.read_bytes()).hexdigest()
    assert metadata["size_bytes"] == path.stat().st_size
    assert len(truth["pages"]) == definition["expected_pages"]
    assert truth["languages"]
    for page in truth["pages"]:
        assert page["width"] > 0 and page["height"] > 0
        assert page["languages"]
        assert all(
            len(box) == 4 and box[0] <= box[2] and box[1] <= box[3]
            for box in page["images"] + [block["bbox"] for block in page["blocks"]]
        )
    if definition["behavior"] == "reject":
        with pytest.raises(EngineError, match=definition["expected_error"]):
            open_pdf(path)
        return
    assert any(page["text"] for page in truth["pages"])
    with open_pdf(path) as document:
        assert len(document) == len(truth["pages"])
        for source, expected in zip(document, truth["pages"], strict=True):
            assert source.rect.width == pytest.approx(expected["width"], abs=.1)
            assert source.rect.height == pytest.approx(expected["height"], abs=.1)
            if expected["scan_background"] and definition["id"] != "PDF-058":
                assert not source.get_text().strip()
                assert source.get_image_info()


def test_ground_truth_preserves_intentional_reading_order(tmp_path):
    path = tmp_path / "columns.pdf"
    metadata = generate("PDF-003", path)
    expected = metadata["ground_truth"]["pages"][0]["text"]
    assert expected.index("Left notes") < expected.index("Right notes")
    with pymupdf.open(path) as document:
        content_stream_order = document[0].get_text(sort=False)
    assert content_stream_order.index("Right notes") < content_stream_order.index("Left notes")


def test_ground_truth_distinguishes_digital_scan_and_repeated_page_furniture(tmp_path):
    mixed = generate("PDF-021", tmp_path / "mixed.pdf")["ground_truth"]
    assert [page["ocr_required"] for page in mixed["pages"]] == [False, True]
    assert "Certificate" in mixed["pages"][1]["body_text"]
    rtl = generate("PDF-060", tmp_path / "arabic.pdf")["ground_truth"]
    assert rtl["features"]["rtl"] == 4
    assert "مختبر" in rtl["pages"][0]["body_text"]
    running = generate("PDF-009", tmp_path / "running.pdf")["ground_truth"]
    assert running["features"]["headers"] == running["features"]["footers"] == 4
    assert running["pages"][0]["header_text"] == "BLUE HARBOR QUALITY LAB"
    assert running["pages"][0]["footer_text"].endswith("1")
    assert "BLUE HARBOR QUALITY LAB" not in running["pages"][0]["body_text"]


def test_original_material_is_repeatable_for_content_fixtures(tmp_path):
    for case_id in ("PDF-003", "PDF-008", "PDF-020", "PDF-052"):
        first = generate(case_id, tmp_path / f"{case_id}-first.pdf")
        second = generate(case_id, tmp_path / f"{case_id}-second.pdf")
        assert first == second


def test_signature_fixture_contains_detached_cms_and_complete_byte_ranges(tmp_path):
    path = tmp_path / "signed.pdf"
    metadata = generate("PDF-029", path)
    assert metadata["ground_truth"]["features"]["signatures"] == 1
    data = path.read_bytes()
    match = re.search(rb"/ByteRange\s*\[\s*0\s+(\d+)\s+(\d+)\s+(\d+)\s*\]", data)
    assert match
    start, end, after = map(int, match.groups())
    assert end + after == len(data)
    assert data[start:start + 1] == b"<"
    assert data[end - 1:end] == b">"
    contents = bytes.fromhex(data[start + 1:end - 1].decode())
    length_octets = contents[1] & 0x7f if contents[1] & 0x80 else 0
    body_size = int.from_bytes(contents[2:2 + length_octets], "big") if length_octets else contents[1]
    certificates = load_der_pkcs7_certificates(contents[:2 + length_octets + body_size])
    assert len(certificates) == 1
    assert certificates[0].subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "Blue Harbor Synthetic QA"
    with pymupdf.open(path) as document:
        assert document.get_sigflags() == 3
        assert [item.field_type for item in document[0].widgets()] == [pymupdf.PDF_WIDGET_TYPE_SIGNATURE]
