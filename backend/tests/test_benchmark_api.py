"""Integration tests for the PDF2DOCX-BENCH administrative API, datasets, runs, and reports."""

from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from docx import Document
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.benchmark.configuration import THRESHOLDS, WEIGHTS
from app.benchmark.fixtures import DATASET_VERSION, catalog
from app.benchmark.tasks import seed_dataset
from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine, make_engine
from app.core.rate_limit import local_limits
from app.main import app
from app.services.storage import storage

PREFIX = "/api/v1/benchmarks"
AUTH_PREFIX = "/api/v1/auth"
ADMIN = {"email": "admin@example.com", "password": "admin-example-password"}
MEMBER = {"email": "member@example.com", "password": "member-example-password"}


@pytest.fixture
def bench_client(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "celery_task_always_eager", True)
    monkeypatch.setattr(settings, "cookie_secure", False)
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "objects")
    monkeypatch.setattr(settings, "work_dir", tmp_path / "work")
    monkeypatch.setattr(settings, "clamav_required", False)
    monkeypatch.setattr(settings, "clamav_host", None)
    monkeypatch.setattr(settings, "admin_email", ADMIN["email"])
    monkeypatch.setattr(settings, "admin_password", ADMIN["password"])
    monkeypatch.setattr(settings, "max_upload_mb", 10)
    monkeypatch.setattr(settings, "max_pages", 50)
    monkeypatch.setattr(settings, "daily_conversion_limit", 40)
    test_engine = make_engine(f"sqlite:///{tmp_path / 'bench-test.sqlite'}")
    Base.metadata.create_all(test_engine)
    SessionLocal.configure(bind=test_engine)
    storage.cache_clear()
    local_limits.clear()
    with TestClient(app) as client:
        yield client
    SessionLocal.configure(bind=engine)
    storage.cache_clear()
    test_engine.dispose()


def login_admin(client: TestClient) -> None:
    response = client.post(f"{AUTH_PREFIX}/login", json=ADMIN)
    assert response.status_code == 200, response.text


def login_member(client: TestClient) -> None:
    client.post(f"{AUTH_PREFIX}/register", json=MEMBER)
    response = client.post(f"{AUTH_PREFIX}/login", json=MEMBER)
    assert response.status_code == 200, response.text


def sample_docx_bytes(text: str = "Reference converted document") -> bytes:
    buffer = BytesIO()
    doc = Document()
    doc.add_paragraph(text)
    doc.save(buffer)
    return buffer.getvalue()


def sample_pdf_bytes(text: str = "Test document") -> bytes:
    with pymupdf.open() as doc:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 100), text, fontsize=12)
        return doc.tobytes()


def test_configuration_requires_admin_and_returns_spec_weights_and_thresholds(bench_client: TestClient):
    unauth = bench_client.get(f"{PREFIX}/configuration")
    assert unauth.status_code in {401, 403}

    login_member(bench_client)
    forbidden = bench_client.get(f"{PREFIX}/configuration")
    assert forbidden.status_code == 403

    login_admin(bench_client)
    res = bench_client.get(f"{PREFIX}/configuration")
    assert res.status_code == 200, res.text
    config = res.json()

    assert config["weights"] == WEIGHTS
    assert sum(config["weights"].values()) == 100
    assert config["weights"]["text_accuracy"] == 20
    assert config["weights"]["layout_preservation"] == 20
    assert config["weights"]["tables_formatting"] == 15
    assert config["weights"]["images_graphics"] == 10
    assert config["weights"]["ocr_performance"] == 10
    assert config["weights"]["docx_compatibility"] == 10
    assert config["weights"]["performance"] == 5
    assert config["weights"]["reliability"] == 4
    assert config["weights"]["security"] == 4
    assert config["weights"]["language_support"] == 2

    assert config["thresholds"] == THRESHOLDS
    assert config["thresholds"]["text_accuracy"] == 0.99
    assert config["thresholds"]["ocr_accuracy"] == 0.97
    assert config["thresholds"]["layout_similarity"] == 0.95
    assert config["thresholds"]["docx_valid"] == 1.0


def test_synthetic_dataset_creation_and_case_inspection(bench_client: TestClient):
    login_admin(bench_client)

    create_res = bench_client.post(f"{PREFIX}/datasets/synthetic")
    assert create_res.status_code == 202, create_res.text
    dataset = create_res.json()
    dataset_id = dataset["id"]

    assert dataset["name"] == "Synthetic PDF corpus"
    assert dataset["version"] == DATASET_VERSION

    list_res = bench_client.get(f"{PREFIX}/datasets")
    assert list_res.status_code == 200
    assert any(d["id"] == dataset_id for d in list_res.json()["datasets"])

    detail_res = bench_client.get(f"{PREFIX}/datasets/{dataset_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["locked"] is True
    assert detail["status"] == "ready"
    assert detail["case_count"] == 100
    assert detail["manifest_sha256"] is not None
    cases = detail["cases"]
    assert len(cases) == 100
    case_ids = [c["case_id"] for c in cases]
    assert case_ids == [f"PDF-{i:03}" for i in range(1, 101)]

    case_res = bench_client.get(f"{PREFIX}/datasets/{dataset_id}/cases/PDF-001")
    assert case_res.status_code == 200
    case_data = case_res.json()
    assert case_data["case_id"] == "PDF-001"
    assert case_data["category"] == "digital"
    assert case_data["behavior"] == "convert"
    assert len(case_data["ground_truth"]["pages"]) == 1

    source_res = bench_client.get(f"{PREFIX}/datasets/{dataset_id}/cases/PDF-001/source")
    assert source_res.status_code == 200
    assert source_res.headers["content-type"] == "application/pdf"
    assert source_res.content.startswith(b"%PDF")


def test_reference_upload_and_download(bench_client: TestClient):
    login_admin(bench_client)

    create_res = bench_client.post(f"{PREFIX}/datasets/synthetic")
    dataset_id = create_res.json()["id"]

    case_info = bench_client.get(f"{PREFIX}/datasets/{dataset_id}/cases/PDF-001").json()
    source_sha = case_info["sha256"]

    ref_docx = sample_docx_bytes("Commercial iLovePDF converted test output")
    upload_res = bench_client.post(
        f"{PREFIX}/datasets/{dataset_id}/cases/PDF-001/reference",
        files={"file": ("reference-ilovepdf.docx", ref_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"source_sha256": source_sha, "provider": "iLovePDF", "duration_seconds": "2.45", "notes": "Reference baseline run from iLovePDF"},
    )
    assert upload_res.status_code == 201, upload_res.text
    ref_data = upload_res.json()
    ref_id = ref_data["id"]
    assert ref_data["provider"] == "iLovePDF"
    assert ref_data["duration_seconds"] == 2.45
    assert ref_data["notes"] == "Reference baseline run from iLovePDF"
    assert ref_data["size_bytes"] == len(ref_docx)

    case_res = bench_client.get(f"{PREFIX}/datasets/{dataset_id}/cases/PDF-001")
    assert case_res.status_code == 200
    assert case_res.json()["has_reference"] is True
    assert case_res.json()["reference"]["provider"] == "iLovePDF"

    download_res = bench_client.get(f"{PREFIX}/datasets/{dataset_id}/cases/PDF-001/references/{ref_id}")
    assert download_res.status_code == 200
    assert download_res.content == ref_docx


def test_benchmark_run_lifecycle_reports_and_rerun(bench_client: TestClient):
    login_admin(bench_client)

    create_res = bench_client.post(f"{PREFIX}/datasets/synthetic")
    dataset_id = create_res.json()["id"]

    run_req = {
        "dataset_id": dataset_id,
        "name": "Integration Test Benchmark Run",
        "case_ids": ["PDF-001", "PDF-024"],
        "max_visual_pages": 2,
        "timeout_seconds": 60,
    }
    run_res = bench_client.post(f"{PREFIX}/runs", json=run_req)
    assert run_res.status_code == 202, run_res.text
    run_data = run_res.json()
    run_id = run_data["id"]
    assert run_data["total"] == 2

    get_run = bench_client.get(f"{PREFIX}/runs/{run_id}")
    assert get_run.status_code == 200
    run_detail = get_run.json()
    assert run_detail["status"] == "completed"
    summary = run_detail["summary"]
    assert summary is not None
    assert summary["total"] == 2
    assert summary["successful_conversions"] == 1
    assert "overall_score" in summary
    assert "category_scores" in summary
    assert len(summary["security"]) == 5
    assert all(chk["passed"] for chk in summary["security"])

    res_pdf1 = bench_client.get(f"{PREFIX}/runs/{run_id}/results/PDF-001")
    assert res_pdf1.status_code == 200
    pdf1_data = res_pdf1.json()
    assert pdf1_data["case_id"] == "PDF-001"
    assert pdf1_data["status"] == "completed"
    assert pdf1_data["conversion_ok"] is True
    assert pdf1_data["metrics"]["docx_valid"] is True
    assert pdf1_data["metrics"]["text_accuracy"] is not None

    res_pdf24 = bench_client.get(f"{PREFIX}/runs/{run_id}/results/PDF-024")
    assert res_pdf24.status_code == 200
    pdf24_data = res_pdf24.json()
    assert pdf24_data["case_id"] == "PDF-024"
    assert pdf24_data["behavior"] == "reject"
    assert pdf24_data["passed"] is True
    assert pdf24_data["metrics"]["expected_rejection"] == 1.0

    json_report = bench_client.get(f"{PREFIX}/runs/{run_id}/reports/json")
    assert json_report.status_code == 200
    assert json_report.headers["content-type"].startswith("application/json")
    json_payload = json_report.json()
    assert json_payload["run"]["id"] == run_id
    assert "summary" in json_payload["run"]
    assert len(json_payload["results"]) == 2

    csv_report = bench_client.get(f"{PREFIX}/runs/{run_id}/reports/csv")
    assert csv_report.status_code == 200
    assert csv_report.headers["content-type"].startswith("text/csv")
    csv_text = csv_report.text
    assert "case_id,category,status,passed,score" in csv_text
    assert "PDF-001" in csv_text
    assert "PDF-024" in csv_text

    html_report = bench_client.get(f"{PREFIX}/runs/{run_id}/reports/html")
    assert html_report.status_code == 200
    assert html_report.headers["content-type"].startswith("text/html")
    html_text = html_report.text
    assert "<!doctype html>" in html_text
    assert "PDF2DOCX-BENCH report" in html_text
    assert "Content-Security-Policy" in html_text

    pdf_report = bench_client.get(f"{PREFIX}/runs/{run_id}/reports/pdf")
    assert pdf_report.status_code == 200
    assert pdf_report.headers["content-type"].startswith("application/pdf")
    assert pdf_report.content.startswith(b"%PDF")

    rerun_res = bench_client.post(f"{PREFIX}/runs/{run_id}/rerun", json={"failed_only": False})
    assert rerun_res.status_code == 202
    child_run = rerun_res.json()
    assert child_run["parent_id"] == run_id
    assert child_run["status"] in {"queued", "running", "completed"}


def test_manual_dataset_creation_and_upload(bench_client: TestClient):
    login_admin(bench_client)

    ds_res = bench_client.post(f"{PREFIX}/datasets", json={"name": "Custom QA Dataset", "version": "v1.0"})
    assert ds_res.status_code == 201
    dataset_id = ds_res.json()["id"]

    pdf_data = sample_pdf_bytes("Manual test case content")
    truth = {
        "pages": [{"text": "Manual test case content", "width": 612.0, "height": 792.0}],
        "languages": ["eng"],
        "ocr_required": False,
    }
    case_res = bench_client.post(
        f"{PREFIX}/datasets/{dataset_id}/cases",
        files={"file": ("custom_case.pdf", pdf_data, "application/pdf")},
        data={
            "case_id": "CUSTOM-001",
            "category": "digital",
            "description": "Manual custom digital test case",
            "behavior": "convert",
            "ground_truth": json.dumps(truth),
            "settings": json.dumps({"mode": "editable"}),
        },
    )
    assert case_res.status_code == 201, case_res.text
    case_info = case_res.json()
    assert case_info["case_id"] == "CUSTOM-001"
    assert case_info["category"] == "digital"

    dup_res = bench_client.post(
        f"{PREFIX}/datasets/{dataset_id}/cases",
        files={"file": ("custom_case.pdf", pdf_data, "application/pdf")},
        data={
            "case_id": "CUSTOM-001",
            "category": "digital",
            "description": "Duplicate case ID",
            "behavior": "convert",
            "ground_truth": json.dumps(truth),
        },
    )
    assert dup_res.status_code == 409
