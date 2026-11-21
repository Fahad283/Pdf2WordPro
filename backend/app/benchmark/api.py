"""Administrative API for benchmark datasets, runs, and protected evidence."""

from contextlib import contextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import tempfile
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from app.core.config import get_settings
from app.core.database import get_db, utcnow
from app.core.security import require_admin
from app.services.delivery import attachment
from app.services.files import inspect_upload, work_root
from app.services.malware import scan_file
from app.services.settings import effective_config
from app.services.storage import storage, stream_file

from .configuration import ASSET_TYPES, MAX_DATASET_CASES, TERMINAL, THRESHOLDS, WEIGHTS, BenchmarkOptions, conversion_options
from .models import BenchmarkDataset, BenchmarkDocument, BenchmarkReference, BenchmarkResult, BenchmarkRun
from .reports import FORMATS, export_report
from .tasks import enqueue, manifest_digest
from .store import checksum, publish_assets, staged_assets

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"], dependencies=[Depends(require_admin)])
PREFIX = "/api/v1/benchmarks"
CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}\Z")
CATEGORY = re.compile(r"[a-z0-9][a-z0-9-]{0,59}\Z")


class DatasetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=60)


class TruthPage(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    text: str = Field(max_length=80_000)
    width: float = Field(gt=0, le=15_000)
    height: float = Field(gt=0, le=15_000)
    tables: list = Field(default_factory=list, max_length=100)
    images: list = Field(default_factory=list, max_length=100)
    blocks: list = Field(default_factory=list, max_length=1000)


class TruthInput(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    pages: list[TruthPage] = Field(min_length=1, max_length=1000)
    features: dict[str, int] = Field(default_factory=dict)
    languages: list[str] = Field(default_factory=list, max_length=8)
    ocr_required: bool = False


def _timestamp(value: datetime | None) -> str | None:
    return value.replace(tzinfo=UTC).isoformat() if value else None


def _dataset(db: Session, dataset_id: UUID | str, *, lock: bool = False) -> BenchmarkDataset:
    row = db.get(BenchmarkDataset, str(dataset_id), with_for_update=lock)
    if row is None:
        raise HTTPException(404, "Benchmark dataset not found.")
    return row


def _case(db: Session, dataset_id: UUID | str, case_id: str) -> BenchmarkDocument:
    row = db.scalar(select(BenchmarkDocument).where(
        BenchmarkDocument.dataset_id == str(dataset_id), BenchmarkDocument.case_id == case_id,
    ))
    if row is None:
        raise HTTPException(404, "Benchmark case not found.")
    return row


def _run(db: Session, run_id: UUID | str) -> BenchmarkRun:
    row = db.get(BenchmarkRun, str(run_id))
    if row is None:
        raise HTTPException(404, "Benchmark run not found.")
    return row


def _result(db: Session, run_id: UUID | str, case_id: str) -> BenchmarkResult:
    row = db.scalar(select(BenchmarkResult).where(
        BenchmarkResult.run_id == str(run_id), BenchmarkResult.case_id == case_id,
    ))
    if row is None:
        raise HTTPException(404, "Benchmark result not found.")
    return row


def _results(db: Session, run_id: str, *, detailed: bool = False) -> list[BenchmarkResult]:
    query = select(BenchmarkResult).where(BenchmarkResult.run_id == run_id).order_by(BenchmarkResult.case_id)
    if not detailed:
        query = query.options(defer(BenchmarkResult.details))
    return list(db.scalars(query))


def dataset_view(row: BenchmarkDataset) -> dict:
    return {
        "id": row.id, "name": row.name, "version": row.version, "status": row.status,
        "locked": row.locked, "case_count": row.case_count, "manifest_sha256": row.manifest_sha256,
        "error": row.error, "created_at": _timestamp(row.created_at),
    }


def _latest_references(db: Session, doc_ids: list[str]) -> dict[str, BenchmarkReference]:
    if not doc_ids:
        return {}
    ranked = select(
        BenchmarkReference.id,
        func.row_number().over(partition_by=BenchmarkReference.document_id,
                               order_by=(BenchmarkReference.created_at.desc(), BenchmarkReference.id.desc())).label("position"),
    ).where(BenchmarkReference.document_id.in_(doc_ids)).subquery()
    newest = db.scalars(select(BenchmarkReference).join(ranked, BenchmarkReference.id == ranked.c.id).where(ranked.c.position == 1))
    return {row.document_id: row for row in newest}


def _case_view(row: BenchmarkDocument, reference: BenchmarkReference | None = None, *, detail: bool = False) -> dict:
    view = {
        "id": row.id, "case_id": row.case_id, "category": row.category, "description": row.description,
        "behavior": row.behavior, "sha256": row.sha256, "size_bytes": row.size_bytes,
        "settings": row.settings, "expected_error": row.expected_error, "has_reference": reference is not None,
    }
    if detail:
        route = f"{PREFIX}/datasets/{row.dataset_id}/cases/{row.case_id}"
        view.update(ground_truth=row.ground_truth, source_url=f"{route}/source", reference=None)
        if reference:
            view["reference"] = {
                "id": reference.id,
                "provider": reference.provider, "sha256": reference.sha256, "source_sha256": reference.source_sha256,
                "duration_seconds": reference.duration_seconds, "size_bytes": reference.size_bytes,
                "notes": reference.notes, "created_at": _timestamp(reference.created_at),
                "download_url": f"{route}/references/{reference.id}",
            }
    return view


def _run_view(row: BenchmarkRun, counts: tuple[int, int] = (0, 0)) -> dict:
    return {
        "id": row.id, "dataset_id": row.dataset_id, "dataset_version": row.dataset_version,
        "dataset_sha256": row.dataset_sha256, "application_version": row.application_version,
        "name": row.name, "status": row.status, "total": row.total, "completed": counts[0],
        "failed": counts[1], "summary": row.summary, "configuration": row.config, "parent_id": row.parent_id,
        "created_at": _timestamp(row.created_at), "finished_at": _timestamp(row.finished_at),
    }


def _result_view(row: BenchmarkResult, *, detail: bool = False, include_export_images: bool = False) -> dict:
    view = {
        "case_id": row.case_id, "category": row.category, "behavior": row.behavior,
        "status": row.status, "passed": row.passed, "conversion_ok": row.conversion_ok,
        "score": row.score, "duration_seconds": row.duration_seconds, "error": row.error, "metrics": row.metrics or {},
    }
    if detail:
        data = dict(row.details or {})
        keys = data.pop("asset_keys", {})
        if row.artifact_expires_at and row.artifact_expires_at <= utcnow():
            keys = {}
        route = f"{PREFIX}/runs/{row.run_id}/results/{row.case_id}/assets"
        data["artifacts"] = {"source_pdf": f"{route}/source_pdf", **{
            key: f"{route}/{key}" for key in keys if not key.startswith("reference_")
        }}
        if "reference" in data:
            reference = dict(data["reference"])
            reference["artifacts"] = (
                {"produced_docx": f"{route}/reference_docx"} if row.reference_id else {}
            ) | {
                key.removeprefix("reference_"): f"{route}/{key}" for key in keys if key.startswith("reference_")
            }
            data["reference"] = reference
        view["details"] = data
        if include_export_images:
            view["_image_keys"] = keys
    return view


def _file_response(key: str, filename: str) -> StreamingResponse:
    media = ASSET_TYPES.get(Path(key).suffix, "application/octet-stream")
    headers = {"Content-Disposition": attachment(filename), "X-Content-Type-Options": "nosniff"}
    if media in ("image/png", "image/jpeg"):
        headers["Content-Disposition"] = "inline"
    try:
        reader = storage().open(key)
    except Exception:
        raise HTTPException(503, "The benchmark asset is temporarily unavailable.") from None
    return StreamingResponse(stream_file(reader), media_type=media, headers=headers)


@contextmanager
def _upload(upload: UploadFile, suffix: str, db: Session):
    config = effective_config(db)
    limit = config.max_upload_mb * 1024 * 1024
    if upload.size is not None and upload.size > limit:
        raise HTTPException(413, "The benchmark file exceeds the upload limit.")
    with tempfile.TemporaryDirectory(prefix="bench-upload-", dir=work_root()) as directory:
        path = Path(directory) / f"input{suffix}"
        size = 0
        with path.open("xb") as stream:
            while chunk := upload.file.read(256 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, "The benchmark file exceeds the upload limit.")
                stream.write(chunk)
        if not size:
            raise HTTPException(422, "Upload a nonempty document.")
        scan_file(path)
        yield path, size, config.max_pages


@router.get("/configuration")
def configuration() -> dict:
    return {"weights": WEIGHTS, "thresholds": THRESHOLDS, "max_visual_pages": 20,
            "max_dataset_cases": MAX_DATASET_CASES, "benchmark_version": "1.0.0"}


@router.get("/datasets")
def datasets(db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(BenchmarkDataset).order_by(BenchmarkDataset.created_at.desc()).limit(100))
    return {"datasets": [dataset_view(row) for row in rows]}


@router.post("/datasets", status_code=201)
def create_dataset(options: DatasetInput, db: Session = Depends(get_db)) -> dict:
    row = BenchmarkDataset(name=options.name, version=options.version)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This dataset version already exists.") from None
    return dataset_view(row)


@router.post("/datasets/synthetic", status_code=202)
def synthetic_dataset(db: Session = Depends(get_db)) -> dict:
    from .fixtures import DATASET_VERSION

    name = "Synthetic PDF corpus"
    existing = db.scalar(select(BenchmarkDataset).where(
        BenchmarkDataset.name == name, BenchmarkDataset.version == DATASET_VERSION,
    ).with_for_update())
    if existing is None:
        existing = BenchmarkDataset(name=name, version=DATASET_VERSION, status="queued")
        db.add(existing)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "This fixture revision is already being created.") from None
    elif existing.status == "failed":
        existing.status, existing.error = "queued", None
        existing.updated_at = utcnow()
        db.commit()
    if existing.status == "queued":
        enqueue("seed", existing.id)
        return {**dataset_view(existing), "status": "building"}
    return dataset_view(existing)


@router.get("/datasets/{dataset_id}")
def dataset_detail(dataset_id: UUID, db: Session = Depends(get_db)) -> dict:
    dataset = _dataset(db, dataset_id)
    rows = list(db.scalars(select(BenchmarkDocument).where(
        BenchmarkDocument.dataset_id == dataset.id,
    ).order_by(BenchmarkDocument.case_id)))
    references = _latest_references(db, [row.id for row in rows])
    return {**dataset_view(dataset), "cases": [_case_view(row, references.get(row.id)) for row in rows]}


@router.get("/datasets/{dataset_id}/cases/{case_id}")
def case_detail(dataset_id: UUID, case_id: str, db: Session = Depends(get_db)) -> dict:
    row = _case(db, dataset_id, case_id)
    return _case_view(row, _latest_references(db, [row.id]).get(row.id), detail=True)


@router.post("/datasets/{dataset_id}/cases", status_code=201)
def upload_case(
    dataset_id: UUID, file: UploadFile = File(...), case_id: str = Form(...),
    category: str = Form(...), description: str = Form(...), ground_truth: str = Form(...),
    settings: str = Form("{}"), db: Session = Depends(get_db),
) -> dict:
    dataset = _dataset(db, dataset_id)
    if dataset.status != "ready" or dataset.locked:
        raise HTTPException(409, "Create a new dataset revision to add or change cases.")
    if not CASE_ID.fullmatch(case_id) or not CATEGORY.fullmatch(category) or not 1 <= len(description.strip()) <= 500:
        raise HTTPException(422, "Enter a case ID, category slug, and description.")
    if Path(file.filename or "").suffix.casefold() != ".pdf":
        raise HTTPException(422, "Upload a PDF for the benchmark case.")
    try:
        truth = TruthInput.model_validate_json(ground_truth).model_dump()
        options = conversion_options(json.loads(settings))
        json.dumps(truth, allow_nan=False)
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(422, "Provide valid ground truth and PDF-to-Word settings.") from None
    with _upload(file, ".pdf", db) as (path, size, max_pages):
        _, pages, encrypted = inspect_upload(path, "case.pdf", max_pages)
        if encrypted or pages != len(truth["pages"]):
            raise HTTPException(422, "Use an unencrypted PDF and include ground truth for every page.")
        with staged_assets({"source": path}) as keys:
            dataset = _dataset(db, dataset_id, lock=True)
            db.refresh(dataset)
            if dataset.locked or dataset.case_count >= MAX_DATASET_CASES:
                raise HTTPException(409, "This dataset revision is locked or full.")
            row = BenchmarkDocument(
                dataset_id=dataset.id, case_id=case_id, category=category, description=description.strip(),
                behavior="convert", source_key=keys["source"], sha256=checksum(path), size_bytes=size,
                ground_truth=truth, settings=options,
            )
            try:
                db.add(row)
                dataset.case_count += 1
                dataset.updated_at = utcnow()
                publish_assets(db, keys)
                db.commit()
            except IntegrityError:
                db.rollback()
                raise HTTPException(409, "A case with this ID already exists in the dataset.") from None
    return _case_view(row, detail=True)


@router.get("/datasets/{dataset_id}/cases/{case_id}/source")
def source_file(dataset_id: UUID, case_id: str, db: Session = Depends(get_db)) -> StreamingResponse:
    row = _case(db, dataset_id, case_id)
    return _file_response(row.source_key, f"{row.case_id}.pdf")


@router.post("/datasets/{dataset_id}/cases/{case_id}/reference", status_code=201)
def upload_reference(
    dataset_id: UUID, case_id: str, file: UploadFile = File(...), source_sha256: str = Form(...),
    provider: str = Form("iLovePDF", min_length=1, max_length=100),
    duration_seconds: float | None = Form(None, gt=0, le=86_400),
    notes: str | None = Form(None, max_length=1000), db: Session = Depends(get_db),
) -> dict:
    row = _case(db, dataset_id, case_id)
    if row.behavior != "convert" or source_sha256 != row.sha256:
        raise HTTPException(409, "Reference output must match the case's original PDF checksum.")
    if Path(file.filename or "").suffix.casefold() != ".docx":
        raise HTTPException(422, "Upload the reference as a DOCX file.")
    with _upload(file, ".docx", db) as (path, size, max_pages):
        inspect_upload(path, "reference.docx", max_pages)
        with staged_assets({"reference": path}) as keys:
            reference = BenchmarkReference(
                document_id=row.id, provider=provider.strip() or "iLovePDF", storage_key=keys["reference"],
                sha256=checksum(path), source_sha256=source_sha256, size_bytes=size,
                duration_seconds=duration_seconds, notes=notes,
            )
            db.add(reference)
            publish_assets(db, keys)
            db.commit()
    return _case_view(row, reference, detail=True)["reference"]


@router.get("/datasets/{dataset_id}/cases/{case_id}/references/{reference_id}")
def reference_file(dataset_id: UUID, case_id: str, reference_id: UUID, db: Session = Depends(get_db)) -> StreamingResponse:
    case = _case(db, dataset_id, case_id)
    row = db.get(BenchmarkReference, str(reference_id))
    if row is None or row.document_id != case.id:
        raise HTTPException(404, "Reference output not found.")
    return _file_response(row.storage_key, f"{case.case_id}-reference.docx")


def create_run(db: Session, options: BenchmarkOptions, *, parent: BenchmarkRun | None = None) -> BenchmarkRun:
    dataset = _dataset(db, options.dataset_id, lock=True)
    if dataset.status != "ready":
        raise HTTPException(409, "Wait until the dataset is ready.")
    all_cases = list(db.scalars(select(BenchmarkDocument).where(
        BenchmarkDocument.dataset_id == dataset.id,
    ).order_by(BenchmarkDocument.case_id)))
    selected = [row for row in all_cases if (
        (options.category is None or row.category == options.category)
        and (options.case_ids is None or row.case_id in options.case_ids)
    )]
    if not selected or (options.case_ids is not None and len(selected) != len(set(options.case_ids))):
        raise HTTPException(422, "Select existing cases from this dataset and category.")
    if db.scalar(select(func.count()).select_from(BenchmarkRun).where(BenchmarkRun.status.in_(("queued", "running")))) >= 2:
        raise HTTPException(409, "Two benchmark runs are already active. Wait for one to finish.")
    dataset.locked = True
    dataset.manifest_sha256 = dataset.manifest_sha256 or manifest_digest(all_cases)
    reference_ids = {key: row.id for key, row in _latest_references(db, [case.id for case in selected]).items()}
    if parent is not None:
        reference_ids = {row.document_id: row.reference_id for row in _results(db, parent.id)}
    config = options.model_dump(exclude={"name", "dataset_id"})
    config.update(case_ids=[item.case_id for item in selected], max_pages=effective_config(db).max_pages)
    if parent:
        config["max_pages"] = parent.config["max_pages"]
    run = BenchmarkRun(
        dataset_id=dataset.id, dataset_version=dataset.version, dataset_sha256=dataset.manifest_sha256,
        application_version=get_settings().benchmark_application_version, name=options.name,
        config=config, total=len(selected), parent_id=parent.id if parent else None,
    )
    db.add(run)
    db.flush()
    for case in selected:
        db.add(BenchmarkResult(run_id=run.id, document_id=case.id, case_id=case.case_id, category=case.category,
                               behavior=case.behavior, reference_id=reference_ids.get(case.id)))
    db.commit()
    enqueue("dispatch", run.id)
    return run


@router.get("/runs")
def list_runs(db: Session = Depends(get_db)) -> dict:
    rows = list(db.scalars(select(BenchmarkRun).order_by(BenchmarkRun.created_at.desc()).limit(60)))
    counts: dict[str, tuple[int, int]] = {}
    if rows:
        for run_id, done, failed in db.execute(select(
            BenchmarkResult.run_id, func.count().filter(BenchmarkResult.status.in_(TERMINAL)),
            func.count().filter(BenchmarkResult.passed.is_(False)),
        ).where(BenchmarkResult.run_id.in_([row.id for row in rows])).group_by(BenchmarkResult.run_id)):
            counts[run_id] = (done, failed)
    return {"runs": [_run_view(row, counts.get(row.id, (0, 0))) for row in rows]}


@router.post("/runs", status_code=202)
def start_run(options: BenchmarkOptions, db: Session = Depends(get_db)) -> dict:
    return _run_view(create_run(db, options))


@router.get("/runs/{run_id}")
def run_detail(run_id: UUID, db: Session = Depends(get_db)) -> dict:
    run = _run(db, run_id)
    rows = _results(db, run.id)
    view = _run_view(run, (sum(row.status in TERMINAL for row in rows), sum(row.passed is False for row in rows)))
    return {**view, "results": [_result_view(row) for row in rows]}


@router.post("/runs/{run_id}/rerun", status_code=202)
def rerun_failures(run_id: UUID, db: Session = Depends(get_db)) -> dict:
    previous = _run(db, run_id)
    if previous.status not in TERMINAL:
        raise HTTPException(409, "Wait until the benchmark has finished.")
    failed = [row.case_id for row in _results(db, previous.id) if row.passed is False]
    if not failed:
        raise HTTPException(409, "This run has no failed cases to rerun.")
    config = {key: value for key, value in previous.config.items() if key in BenchmarkOptions.model_fields}
    options = BenchmarkOptions(**{**config, "case_ids": failed, "name": f"Rerun · {previous.name[:90]}",
                                 "dataset_id": previous.dataset_id})
    return _run_view(create_run(db, options, parent=previous))


@router.get("/runs/{run_id}/results/{case_id}")
def result_detail(run_id: UUID, case_id: str, db: Session = Depends(get_db)) -> dict:
    return _result_view(_result(db, run_id, case_id), detail=True)


@router.get("/runs/{run_id}/results/{case_id}/assets/{role}")
def result_asset(run_id: UUID, case_id: str, role: str, db: Session = Depends(get_db)) -> StreamingResponse:
    row = _result(db, run_id, case_id)
    if role == "source_pdf":
        document = db.get(BenchmarkDocument, row.document_id)
        return _file_response(document.source_key, f"{case_id}.pdf")
    if role == "reference_docx" and row.reference_id:
        reference = db.get(BenchmarkReference, row.reference_id)
        return _file_response(reference.storage_key, f"{case_id}-reference.docx")
    if row.artifact_expires_at and row.artifact_expires_at <= utcnow():
        raise HTTPException(410, "Benchmark diagnostic artifacts have expired.")
    key = (row.details or {}).get("asset_keys", {}).get(role)
    if key is None:
        raise HTTPException(404, "Benchmark artifact not found.")
    return _file_response(key, f"{case_id}-{role}{Path(key).suffix}")


@router.get("/runs/{run_id}/reports/{format}")
def report(run_id: UUID, format: str, db: Session = Depends(get_db)) -> Response:
    run = _run(db, run_id)
    if format not in FORMATS:
        raise HTTPException(422, "Choose PDF, HTML, JSON, or CSV.")
    if run.status not in TERMINAL or run.summary is None:
        raise HTTPException(409, "The benchmark report is available after execution.")
    rows = _results(db, run.id, detailed=True)
    view = _run_view(run, (run.total, sum(row.passed is False for row in rows)))
    body = export_report(format, view, [_result_view(row, detail=True, include_export_images=True) for row in rows])
    return Response(body, media_type=FORMATS[format], headers={
        "Content-Disposition": attachment(f"pdf2docx-bench-{run.id}.{format}"),
    })
