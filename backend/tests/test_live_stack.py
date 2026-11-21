"""Real HTTP acceptance tests for an already running Compose stack."""

from io import BytesIO
import json
import os
import time
from zipfile import ZipFile

from docx import Document
import httpx
from PIL import Image, ImageDraw
import pymupdf
import pytest

LIVE_URL = os.environ.get("PDF_PRO_LIVE_URL")
pytestmark = pytest.mark.skipif(not LIVE_URL, reason="Set PDF_PRO_LIVE_URL to test a running stack")


@pytest.fixture
def live():
    jobs, uploads = [], []
    with httpx.Client(base_url=f"{LIVE_URL.rstrip('/')}/api/v1/", timeout=35) as client:
        yield client, jobs, uploads
        for job_id in jobs:
            client.delete(f"conversions/{job_id}")
        for file_id in uploads:
            client.delete(f"files/{file_id}")


def digital_pdf():
    with pymupdf.open() as document:
        page = document.new_page(width=612, height=792)
        page.insert_text((60, 100), "PDF to Word Pro acceptance report", fontsize=22)
        page.insert_text((60, 145), "A real document with selectable text and formatting.", fontsize=14)
        return document.tobytes()


def scanned_pdf():
    image = Image.new("RGB", (1200, 400), "white")
    ImageDraw.Draw(image).text((90, 148), "SCANNED ACCEPTANCE REPORT", fill="black", font_size=56)
    raster = BytesIO()
    image.save(raster, format="PNG")
    with pymupdf.open() as document:
        page = document.new_page(width=600, height=200)
        page.insert_image(page.rect, stream=raster.getvalue())
        return document.tobytes()


def upload(live, name, body):
    client, _, uploads = live
    response = client.post("files/upload", files={"file": (name, body, "application/pdf")})
    assert response.status_code == 201, response.text
    record = response.json()
    uploads.append(record["id"])
    assert record["page_count"] == 1
    return record


def submit(live, record, **settings):
    client, jobs, _ = live
    response = client.post("conversions", json={"file_ids": [record["id"]], "settings": settings})
    assert response.status_code == 202, response.text
    job = response.json()
    jobs.append(job["id"])
    return job


def wait(client, job_id):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = client.get(f"conversions/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in ("completed", "failed", "cancelled"):
            assert job["status"] == "completed", job
            assert job["progress"] == 100
            return job
        time.sleep(.5)
    pytest.fail(f"Job {job_id} did not complete in two minutes")


def download(client, job_id):
    response = client.get(f"conversions/{job_id}/download")
    assert response.status_code == 200, response.text
    assert "attachment;" in response.headers["content-disposition"]
    return response.content


def test_live_digital_modes_events_and_permissions(live):
    client, _, _ = live
    health = client.get("health")
    assert health.status_code == 200, health.text
    for name in ("database", "redis", "storage"):
        assert health.json()["checks"][name] == "ok", health.json()
    invalid = client.post("files/upload", files={"file": ("damaged.pdf", b"not a PDF", "application/pdf")})
    assert invalid.status_code == 422, invalid.text
    record = upload(live, "../acceptance.pdf", digital_pdf())
    assert record["original_filename"] == "acceptance.pdf"
    inspection = client.post("pdf/inspect", json={"file_id": record["id"]})
    assert inspection.status_code == 200, inspection.text
    assert inspection.json()["page_count"] == 1

    editable = submit(live, record, mode="editable")
    seen = []
    with client.stream("GET", f"conversions/{editable['id']}/events") as events:
        assert events.status_code == 200
        assert events.headers["content-type"].startswith("text/event-stream")
        for line in events.iter_lines():
            if line.startswith("data: "):
                seen.append(json.loads(line[6:]))
    assert seen[-1]["status"] == "completed", seen[-1]
    assert seen[-1]["progress"] == 100
    paragraphs = Document(BytesIO(download(client, editable["id"]))).paragraphs
    assert any("acceptance report" in paragraph.text for paragraph in paragraphs)
    with httpx.Client(base_url=client.base_url) as outsider:
        assert outsider.get(f"conversions/{editable['id']}/download").status_code == 404

    flowing = submit(live, record, mode="flowing")
    visual = submit(live, record, mode="visual")
    for job in (flowing, visual):
        wait(client, job["id"])
    flowing_docx = Document(BytesIO(download(client, flowing["id"])))
    visual_docx = Document(BytesIO(download(client, visual["id"])))
    assert "selectable text" in " ".join(paragraph.text for paragraph in flowing_docx.paragraphs)
    assert not any(paragraph.text.strip() for paragraph in visual_docx.paragraphs)
    assert len(visual_docx.inline_shapes) == 1

    assert client.delete(f"conversions/{editable['id']}").status_code == 204
    assert client.get(f"conversions/{editable['id']}/download").status_code == 404


def test_live_ocr_batch_and_zip(live):
    client, jobs, _ = live
    digital = upload(live, "digital.pdf", digital_pdf())
    scan = upload(live, "scan.pdf", scanned_pdf())
    response = client.post("conversions/batch", json={
        "file_ids": [digital["id"], scan["id"]],
        "settings": {"languages": ["eng"], "ocr": "auto"},
    })
    assert response.status_code == 202, response.text
    batch = response.json()
    for job in batch["jobs"]:
        jobs.append(job["id"])
        wait(client, job["id"])
    zipped = client.get(f"conversions/batches/{batch['id']}/download")
    assert zipped.status_code == 200, zipped.text
    with ZipFile(BytesIO(zipped.content)) as archive:
        assert set(archive.namelist()) == {"digital.docx", "scan.docx"}
        assert archive.testzip() is None
        doc = Document(BytesIO(archive.read("scan.docx")))
    assert "SCANNED ACCEPTANCE REPORT" in " ".join(paragraph.text for paragraph in doc.paragraphs)
