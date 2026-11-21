"""Celery execution and recovery for the dedicated benchmark queue."""

from contextlib import ExitStack
from datetime import timedelta
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.database import SessionLocal, utcnow
from app.services.files import work_root
from app.services.storage import storage
from app.workers.celery_app import celery_app

from .configuration import QUEUE, TERMINAL
from .defensive_checks import run_checks
from .execution import CaseTimeout, asset_paths, evaluate_isolated
from .models import BenchmarkDataset, BenchmarkDocument, BenchmarkReference, BenchmarkResult, BenchmarkRun
from .scoring import case_verdict, summarize
from .store import checksum, publish_assets, staged_assets

log = logging.getLogger(__name__)


def manifest_digest(documents: list[BenchmarkDocument]) -> str:
    from hashlib import sha256

    manifest = [
        {"id": row.case_id, "sha256": row.sha256, "category": row.category, "description": row.description,
         "behavior": row.behavior, "settings": row.settings, "truth": row.ground_truth,
         "expected_error": row.expected_error}
        for row in sorted(documents, key=lambda document: document.case_id)
    ]
    return sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def enqueue(task: str, *args: str) -> bool:
    if get_settings().celery_task_always_eager:
        handlers = {
            "seed": seed_dataset,
            "dispatch": dispatch_run,
            "case": run_case,
            "recover": recover_benchmarks,
        }
        handler = handlers.get(task)
        if handler:
            handler(*args)
            return True
    try:
        celery_app.send_task(f"pdfpro.benchmark.{task}", args=args, queue=QUEUE)
        return True
    except Exception as exc:
        log.warning("benchmark_enqueue_deferred", extra={"error_type": type(exc).__name__})
        return False


@celery_app.task(name="pdfpro.benchmark.seed")
def seed_dataset(dataset_id: str) -> None:
    from .fixtures import catalog, generate

    with SessionLocal() as db:
        claimed = db.execute(update(BenchmarkDataset).where(
            BenchmarkDataset.id == dataset_id, BenchmarkDataset.status == "queued",
        ).values(status="building", updated_at=utcnow())).rowcount
        db.commit()
    if not claimed:
        return
    try:
        with TemporaryDirectory(prefix="bench-seed-", dir=work_root()) as directory:
            root = Path(directory)
            entries = []
            for definition in catalog():
                path = root / f"{definition['id']}.pdf"
                record = generate(definition["id"], path)
                if checksum(path) != record["sha256"]:
                    raise RuntimeError("The fixture changed during dataset generation.")
                entries.append((record, path))
            with staged_assets({item["id"]: path for item, path in entries}) as assets:
                with SessionLocal() as db:
                    dataset = db.get(BenchmarkDataset, dataset_id, with_for_update=True)
                    if not dataset or dataset.status != "building":
                        return
                    rows = [
                        BenchmarkDocument(
                            dataset_id=dataset_id, case_id=item["id"], category=item["category"],
                            description=item["description"], behavior=item["behavior"],
                            expected_error=item.get("expected_error"), source_key=assets[item["id"]],
                            sha256=item["sha256"], size_bytes=item["size_bytes"],
                            ground_truth=item["ground_truth"], settings=item["settings"],
                        )
                        for item, _ in entries
                    ]
                    db.add_all(rows)
                    dataset.case_count = len(rows)
                    dataset.manifest_sha256 = manifest_digest(rows)
                    dataset.locked = True
                    dataset.status = "ready"
                    dataset.updated_at = utcnow()
                    publish_assets(db, assets)
                    db.commit()
    except Exception as exc:
        log.error("benchmark_seed_failed", extra={"error_type": type(exc).__name__})
        with SessionLocal() as db:
            db.execute(update(BenchmarkDataset).where(
                BenchmarkDataset.id == dataset_id, BenchmarkDataset.status == "building",
            ).values(status="failed", error="The fixture dataset could not be created.", updated_at=utcnow()))
            db.commit()


@celery_app.task(name="pdfpro.benchmark.dispatch")
def dispatch_run(run_id: str) -> None:
    with SessionLocal() as db:
        pending = list(db.scalars(select(BenchmarkResult.id).where(
            BenchmarkResult.run_id == run_id, BenchmarkResult.status == "queued",
            (BenchmarkResult.dispatched_at.is_(None)
             | (BenchmarkResult.dispatched_at <= utcnow() - timedelta(minutes=15))),
        ).order_by(BenchmarkResult.case_id)))
    for result_id in pending:
        if enqueue("case", result_id):
            with SessionLocal() as db:
                db.execute(update(BenchmarkResult).where(
                    BenchmarkResult.id == result_id, BenchmarkResult.status == "queued",
                ).values(dispatched_at=utcnow()))
                db.commit()


def _finalize(run_id: str) -> None:
    with SessionLocal() as db:
        run = db.get(BenchmarkRun, run_id, with_for_update=True)
        if not run or run.status in TERMINAL:
            return
        results = list(db.scalars(select(BenchmarkResult).where(
            BenchmarkResult.run_id == run_id,
        ).order_by(BenchmarkResult.case_id)))
        if len(results) != run.total or any(row.status not in TERMINAL for row in results):
            return
        candidates = db.scalars(select(BenchmarkRun).where(
            BenchmarkRun.id != run.id, BenchmarkRun.dataset_sha256 == run.dataset_sha256,
            BenchmarkRun.status == "completed", BenchmarkRun.created_at < run.created_at,
        ).order_by(BenchmarkRun.created_at.desc()).limit(12))
        baseline = next((
            {"run_id": previous.id, "overall_score": previous.summary.get("overall_score"), "delta": None}
            for previous in candidates if previous.config == run.config and previous.summary
        ), None)
        run.summary = summarize(results, run.config, run_checks(), baseline)
        run.status = "completed"
        run.finished_at = utcnow()
        db.commit()


def _record(result_id: str, data: dict, config: dict, assets: dict[str, str]) -> None:
    with SessionLocal() as db:
        row = db.get(BenchmarkResult, result_id, with_for_update=True)
        if row is None or row.status != "processing":
            return
        metrics = data.setdefault("metrics", {})
        metrics["reliability"] = float(data.get("execution_ok", False))
        critical = data.setdefault("critical", [])
        score, passed, misses, breakdown = case_verdict(metrics, config, row.behavior, critical)
        row.status = "completed" if data.get("execution_ok") else "failed"
        row.passed = passed and data.get("execution_ok", False)
        row.conversion_ok = data.get("conversion_ok", False)
        row.score, row.metrics = score, metrics
        row.duration_seconds = metrics.get("conversion_seconds", metrics.get("case_seconds"))
        row.error = data.get("error")
        row.updated_at = utcnow()
        row.artifact_expires_at = utcnow() + timedelta(days=get_settings().benchmark_artifact_days)
        row.details = {**data, "category_values": breakdown, "failed_targets": misses, "asset_keys": assets}
        publish_assets(db, assets)
        db.commit()


@celery_app.task(name="pdfpro.benchmark.case")
def run_case(result_id: str) -> None:
    with SessionLocal() as db:
        acquired = db.execute(update(BenchmarkResult).where(
            BenchmarkResult.id == result_id, BenchmarkResult.status == "queued",
        ).values(status="processing", updated_at=utcnow())).rowcount
        if not acquired:
            return
        row = db.get(BenchmarkResult, result_id)
        run_id = row.run_id
        db.execute(update(BenchmarkRun).where(
            BenchmarkRun.id == run_id, BenchmarkRun.status == "queued",
        ).values(status="running"))
        run = db.get(BenchmarkRun, run_id)
        document = db.get(BenchmarkDocument, row.document_id)
        reference = db.get(BenchmarkReference, row.reference_id) if row.reference_id else None
        config = run.config
        run_settings = {
            "settings": {**document.settings, **config["settings"]}, "ground_truth": document.ground_truth,
            "behavior": document.behavior, "expected_error": document.expected_error,
            "timeout_seconds": config["timeout_seconds"], "max_visual_pages": config["max_visual_pages"],
            "max_pages": config["max_pages"],
        }
        db.commit()

    work = None
    try:
        with ExitStack() as stack:
            with TemporaryDirectory(prefix="bench-case-", dir=work_root()) as directory:
                work = Path(directory)
                source = work / "source.pdf"
                storage().download(document.source_key, source)
                if checksum(source) != document.sha256:
                    raise ValueError("Input SHA-256 validation failed.")
                if reference is not None:
                    reference_path = work / "reference.docx"
                    storage().download(reference.storage_key, reference_path)
                    if checksum(reference_path) != reference.sha256:
                        raise ValueError("Reference SHA-256 validation failed.")
                data = evaluate_isolated(work, run_settings)
                if reference is not None:
                    metadata = data.setdefault("reference", {})
                    metadata.update({
                        "provider": reference.provider, "duration_seconds": reference.duration_seconds,
                        "size_bytes": reference.size_bytes, "source_sha256": reference.source_sha256,
                        "sha256": reference.sha256, "notes": reference.notes,
                    })
                data["input_sha256"] = document.sha256
                keys = stack.enter_context(staged_assets(asset_paths(data, work)))
            data.setdefault("metrics", {})["cleanup_rate"] = float(not work.exists())
            _record(result_id, data, config, keys)
    except Exception as exc:
        log.error("benchmark_case_failed", extra={"error_type": type(exc).__name__})
        timed_out = isinstance(exc, (CaseTimeout, SoftTimeLimitExceeded))
        reason = "Benchmark evaluation exceeded its time limit." if timed_out else (
            str(exc) if isinstance(exc, ValueError) and str(exc).endswith("SHA-256 validation failed.")
            else "The benchmark case failed to finish. Inspect the case and run it again."
        )
        _record(result_id, {
            "error": reason, "execution_ok": False, "conversion_ok": False, "critical": [reason],
            "metrics": {"timed_out": timed_out, "cleanup_rate": float(not work.exists()) if work else None},
        }, config, {})
    _finalize(run_id)


def _expire_assets() -> None:
    with SessionLocal() as db:
        expired = db.scalars(select(BenchmarkResult).where(
            BenchmarkResult.artifact_expires_at <= utcnow(),
        ).limit(20).with_for_update(skip_locked=True)).all()
        for row in expired:
            details = dict(row.details or {})
            for key in details.get("asset_keys", {}).values():
                storage().delete(key)
            details["asset_keys"] = {}
            row.details = details
            row.artifact_expires_at = None
        db.commit()


@celery_app.task(name="pdfpro.benchmark.recover")
def recover_benchmarks() -> None:
    now = utcnow()
    with SessionLocal() as db:
        seeds = db.scalars(select(BenchmarkDataset.id).where(
            BenchmarkDataset.status == "queued", BenchmarkDataset.updated_at <= now - timedelta(seconds=45),
        ).limit(5)).all()
        db.execute(update(BenchmarkDataset).where(
            BenchmarkDataset.status == "building", BenchmarkDataset.updated_at <= now - timedelta(minutes=10),
        ).values(status="failed", error="Fixture generation was interrupted. Retry the dataset."))
        stale = db.scalars(select(BenchmarkResult).where(
            BenchmarkResult.status == "processing", BenchmarkResult.updated_at <= now - timedelta(minutes=6),
        ).limit(25).with_for_update(skip_locked=True)).all()
        for row in stale:
            row.status, row.passed, row.conversion_ok = "failed", False, False
            row.error = "The worker stopped before this case finished."
            row.metrics = {"reliability": 0.}
            row.details = {"critical": [row.error], "category_values": {"reliability": 0.}}
        retained = db.scalars(select(BenchmarkRun.id).where(
            BenchmarkRun.status.in_(("queued", "running")),
        ).limit(20)).all()
        db.commit()
    for seed in seeds:
        enqueue("seed", seed)
    for run_id in retained:
        dispatch_run(run_id)
        _finalize(run_id)
    _expire_assets()
