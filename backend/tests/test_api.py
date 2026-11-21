from datetime import timedelta
from io import BytesIO
import shutil
from zipfile import ZipFile

import pymupdf
import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine, make_engine, utcnow
from app.core.rate_limit import local_limits
from app.main import app
from app.models import FileRecord, Job
from app.services.storage import storage
from app.workers.tasks import cleanup_task

PREFIX = "/api/v1"
ADMIN = {"email": "admin@example.com", "password": "admin-example-password"}
MEMBER = {"email": "member@example.com", "password": "member-example-password"}


@pytest.fixture
def client(tmp_path, monkeypatch):
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
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    monkeypatch.setattr(settings, "max_pages", 5)
    monkeypatch.setattr(settings, "daily_conversion_limit", 40)
    test_engine = make_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    Base.metadata.create_all(test_engine)
    SessionLocal.configure(bind=test_engine)
    storage.cache_clear()
    local_limits.clear()
    with TestClient(app) as test_client:
        yield test_client
    SessionLocal.configure(bind=engine)
    storage.cache_clear()
    test_engine.dispose()


def pdf_bytes(text: str = "Editable conversion example", count: int = 1, password: str | None = None) -> bytes:
    with pymupdf.open() as source:
        for index in range(count):
            page = source.new_page()
            page.insert_text((72, 100), f"{text} {index + 1}", fontsize=14)
        if password:
            return source.tobytes(
                encryption=pymupdf.PDF_ENCRYPT_AES_256,
                owner_pw="test-owner-passphrase",
                user_pw=password,
            )
        return source.tobytes()


def upload(client: TestClient, data: bytes, name: str = "example.pdf") -> dict:
    response = client.post(f"{PREFIX}/files/upload", files={"file": (name, data, "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()


def submit(client: TestClient, file_id: str, *, tool: str = "pdf-to-word", **options) -> dict:
    payload = {"file_ids": [file_id], "tool": tool, "settings": options or {"validate_render": False}}
    response = client.post(f"{PREFIX}/conversions", json=payload)
    assert response.status_code == 202, response.text
    return response.json()


def test_private_editable_conversion_progress_and_deletion(client):
    upload_record = upload(client, pdf_bytes(), "../private\\report.pdf")
    assert upload_record["original_filename"] == "report.pdf"
    assert upload_record["page_count"] == 1
    inspect = client.post(f"{PREFIX}/pdf/inspect", json={"file_id": upload_record["id"]})
    assert inspect.json()["page_count"] == 1
    job = submit(client, upload_record["id"])
    assert job["status"] == "completed", job
    assert job["progress"] == 100
    assert job["output_filename"] == "report.docx"
    path = f"{PREFIX}/conversions/{job['id']}"
    assert client.get(path).json()["id"] == job["id"]
    assert "event: status" in client.get(f"{path}/events").text

    with TestClient(app) as other:
        assert other.get(path).status_code == 404
        assert other.get(f"{path}/download").status_code == 404
        assert other.delete(path).status_code == 404
        rejected = other.post(f"{PREFIX}/conversions", json={"file_ids": [upload_record["id"]]})
        assert rejected.status_code == 404

    result = client.get(f"{path}/download")
    assert result.status_code == 200
    assert "report.docx" in result.headers["Content-Disposition"]
    assert "Editable conversion example" in " ".join(
        paragraph.text for paragraph in Document(BytesIO(result.content)).paragraphs
    )
    object_dir = get_settings().storage_dir
    assert len(list(object_dir.iterdir())) == 2
    assert client.delete(path).status_code == 204
    assert not list(object_dir.iterdir())
    assert not list(get_settings().work_dir.iterdir())
    assert client.get(f"{path}/download").status_code == 404


def test_upload_validation_limits_and_csrf(client):
    endpoint = f"{PREFIX}/files/upload"
    invalid = client.post(endpoint, files={"file": ("fake.pdf", b"<html>no", "application/pdf")})
    assert invalid.status_code == 422
    corrupt = client.post(endpoint, files={"file": ("fake.pdf", b"%PDF-1.7\nmissing data", "application/pdf")})
    assert corrupt.status_code == 422
    too_long = client.post(endpoint, files={"file": ("big.pdf", pdf_bytes(count=6), "application/pdf")})
    assert too_long.status_code == 413
    too_large = client.post(endpoint, files={"file": ("big.pdf", b"%PDF-" + b"0" * (1024 * 1024), "application/pdf")})
    assert too_large.status_code == 413
    cross_site = client.post(
        endpoint,
        files={"file": ("valid.pdf", pdf_bytes(), "application/pdf")},
        headers={"origin": "https://untrusted.example"},
    )
    assert cross_site.status_code == 403
    assert not list(get_settings().storage_dir.glob("*"))


def test_batch_zip_duplicates_and_independent_jobs(client):
    first = upload(client, pdf_bytes("First"), "same.pdf")
    second = upload(client, pdf_bytes("Second"), "same.pdf")
    response = client.post(f"{PREFIX}/conversions/batch", json={
        "file_ids": [first["id"], second["id"]], "settings": {"validate_render": False},
    })
    assert response.status_code == 202, response.text
    batch = response.json()
    assert len(batch["jobs"]) == 2
    assert {job["status"] for job in batch["jobs"]} == {"completed"}
    result = client.get(f"{PREFIX}/conversions/batches/{batch['id']}/download")
    assert result.status_code == 200
    with ZipFile(BytesIO(result.content)) as archive:
        assert set(archive.namelist()) == {"same.docx", "same (2).docx"}
        assert archive.testzip() is None
        for name in archive.namelist():
            assert Document(BytesIO(archive.read(name))).paragraphs


@pytest.mark.skipif(not shutil.which("qpdf"), reason="qpdf is not installed")
def test_password_scoped_to_processing_and_hidden_from_database(client):
    document_password = "document-passphrase"
    source = upload(client, pdf_bytes(password=document_password))
    assert source["encrypted"] is True
    ordinary = client.post(f"{PREFIX}/conversions", json={"file_ids": [source["id"]]})
    assert ordinary.status_code == 422
    failed = submit(client, source["id"], tool="unlock-pdf", password="incorrect-password")
    assert failed["status"] == "failed"
    path = f"{PREFIX}/conversions/{failed['id']}"
    assert client.post(f"{path}/retry").status_code == 422
    succeeded = client.post(f"{path}/retry", json={"password": document_password})
    assert succeeded.status_code == 202
    assert succeeded.json()["status"] == "completed", succeeded.text
    assert document_password not in succeeded.text
    with SessionLocal() as db:
        job = db.get(Job, failed["id"])
        assert job.requires_password
        assert "password" not in job.settings
        assert document_password not in str(job.metrics)
    result = client.get(f"{path}/download")
    with pymupdf.open(stream=result.content, filetype="pdf") as unlocked:
        assert not unlocked.needs_pass
        assert "Editable conversion example" in unlocked[0].get_text()


def test_guest_history_transfer_account_permissions_and_admin_settings(client):
    source = upload(client, pdf_bytes())
    job = submit(client, source["id"])
    assert client.get(f"{PREFIX}/admin/metrics").status_code == 401
    registered = client.post(f"{PREFIX}/auth/register", json=MEMBER)
    assert registered.status_code == 201
    assert {record["id"] for record in client.get(f"{PREFIX}/conversions/history").json()["jobs"]} == {job["id"]}
    assert client.get(f"{PREFIX}/admin/metrics").status_code == 403
    assert client.post(f"{PREFIX}/auth/logout").status_code == 204
    assert client.get(f"{PREFIX}/conversions/{job['id']}").status_code == 404

    assert client.post(f"{PREFIX}/auth/login", json=ADMIN).status_code == 200
    metrics = client.get(f"{PREFIX}/admin/metrics")
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["total_conversions"] == 1
    assert metrics.json()["total_users"] == 2
    assert client.get(f"{PREFIX}/conversions/{job['id']}").status_code == 404
    policy = client.patch(f"{PREFIX}/admin/settings", json={"retention_minutes": 37, "daily_conversion_limit": 1})
    assert policy.status_code == 200
    assert client.get(f"{PREFIX}/config").json()["retention_minutes"] == 37
    account = registered.json()["id"]
    suspended = client.patch(f"{PREFIX}/admin/users/{account}", json={"status": "suspended", "plan": "premium"})
    assert suspended.json()["status"] == "suspended"
    assert client.post(f"{PREFIX}/auth/login", json=MEMBER).status_code == 401


def test_retention_removes_stored_contents_and_denies_download(client):
    uploaded = upload(client, pdf_bytes())
    job = submit(client, uploaded["id"])
    assert job["status"] == "completed"
    with SessionLocal() as db:
        records = db.scalars(select(FileRecord)).all()
        for record in records:
            record.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    cleanup_task()
    assert not list(get_settings().storage_dir.iterdir())
    assert client.get(f"{PREFIX}/conversions/{job['id']}/download").status_code == 410
    assert client.post(f"{PREFIX}/pdf/inspect", json={"file_id": uploaded["id"]}).status_code == 410


def test_cancelled_job_can_be_retried_without_stale_attempt_publication(client, monkeypatch):
    from app.services import jobs
    from app.workers.tasks import execute_job

    uploaded = upload(client, pdf_bytes())
    original_enqueue = jobs._enqueue
    with monkeypatch.context() as hold:
        hold.setattr(jobs, "_enqueue", lambda db, job, password: job)
        queued = submit(client, uploaded["id"])
    assert queued["status"] == "queued"
    job_id = queued["id"]
    old_attempt = None
    with SessionLocal() as db:
        old_attempt = db.get(Job, job_id).attempt
    cancelled = client.post(f"{PREFIX}/conversions/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    execute_job(job_id, old_attempt)
    assert client.get(f"{PREFIX}/conversions/{job_id}").json()["status"] == "cancelled"
    assert jobs._enqueue is original_enqueue
    retried = client.post(f"{PREFIX}/conversions/{job_id}/retry")
    assert retried.status_code == 202, retried.text
    assert retried.json()["status"] == "completed"


def test_unpublished_attempt_is_recovered_once(client, monkeypatch):
    from app.services import jobs
    from app.workers import tasks

    upload_record = upload(client, pdf_bytes())
    with monkeypatch.context() as hold:
        hold.setattr(jobs, "_enqueue", lambda db, job, password: job)
        job = submit(client, upload_record["id"])
    task_id = job["id"]
    with SessionLocal() as db:
        pending = db.get(Job, task_id)
        pending.updated_at = utcnow() - timedelta(seconds=90)
        attempt = pending.attempt
        db.commit()

    published = []

    def publish(*, args, task_id, retry):
        published.append((args, task_id, retry))

    monkeypatch.setattr(tasks.conversion_task, "apply_async", publish)
    tasks._recover_unpublished_jobs()
    tasks._recover_unpublished_jobs()
    assert published == [((task_id, attempt), attempt, False)]
    tasks.execute_job(task_id, attempt)
    tasks.execute_job(task_id, attempt)
    assert client.get(f"{PREFIX}/conversions/{task_id}").json()["status"] == "completed"
    with SessionLocal() as db:
        assert len(db.scalars(select(FileRecord).where(FileRecord.kind == "output")).all()) == 1


def test_abandoned_objects_are_purged_after_grace(client, tmp_path):
    from app.models import StagedObject
    from app.services.staging import STAGING_GRACE, reserve_object

    old_source = tmp_path / "source.pdf"
    old_source.write_bytes(pdf_bytes())
    with SessionLocal() as db:
        expired = reserve_object(db, ".pdf")
        recent = reserve_object(db, ".pdf")
        db.get(StagedObject, expired).created_at = utcnow() - STAGING_GRACE - timedelta(seconds=1)
        db.commit()
    storage().put(expired, old_source, "application/pdf")
    storage().put(recent, old_source, "application/pdf")

    cleanup_task()

    assert not (get_settings().storage_dir / expired).exists()
    assert (get_settings().storage_dir / recent).is_file()
    with SessionLocal() as db:
        assert db.get(StagedObject, expired) is None
        assert db.get(StagedObject, recent) is not None


def test_chunked_oversize_request_is_rejected_before_upload(client):
    delimiter = "size-test"
    part_headers = (
        f"--{delimiter}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"report.pdf\"\r\n"
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()

    def data():
        yield part_headers
        for _ in range(5):
            yield b"0" * (256 * 1024)
        yield f"\r\n--{delimiter}--\r\n".encode()

    result = client.post(
        f"{PREFIX}/files/upload",
        content=data(),
        headers={"Content-Type": f"multipart/form-data; boundary={delimiter}"},
    )
    assert result.status_code == 413, result.text
    assert not list(get_settings().storage_dir.glob("*"))
