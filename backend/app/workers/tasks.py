import logging
import math
import shutil
import time
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import delete, exists, select, update

from app.core.config import get_settings
from app.core.database import SessionLocal, utcnow
from app.engines import EngineError, convert_pdf
from app.engines.pdf_tools import TOOL_OUTPUTS, run_tool
from app.models import Batch, FileRecord, Job, JobInput, UsageBucket, new_id
from app.services.files import MIME_TYPES, is_available, purge_files, work_root
from app.services.job_secrets import has_password, take_password
from app.services.settings import effective_config
from app.services.staging import commit_reservation, discard_object, recover_staged_objects, reserve_object
from app.services.storage import storage
from app.workers.celery_app import celery_app

settings = get_settings()
logger = logging.getLogger(__name__)
SOURCE_SUFFIX = {mime: extension for extension, mime in MIME_TYPES.items()}


class JobStopped(Exception):
    pass


def _lease(job_id: str, attempt: str, status: str):
    return (
        Job.id == job_id,
        Job.attempt == attempt,
        Job.status == status,
        Job.deleted_at.is_(None),
        Job.expires_at > utcnow(),
    )


def _claim(job_id: str, attempt: str) -> bool:
    with SessionLocal() as db:
        result = db.execute(update(Job).where(*_lease(job_id, attempt, "queued")).values(
            status="processing", progress=1, updated_at=utcnow(),
        ))
        db.commit()
        return result.rowcount == 1


def _progress(job_id: str, attempt: str, value: int) -> None:
    value = min(99, max(1, int(value)))
    with SessionLocal() as db:
        current = db.scalar(select(Job.progress).where(*_lease(job_id, attempt, "processing")))
        if current is None:
            raise JobStopped()
        if value > current:
            db.execute(update(Job).where(*_lease(job_id, attempt, "processing")).values(
                progress=value, updated_at=utcnow(),
            ))
            db.commit()


def _fail(job_id: str, attempt: str, message: str, duration: float) -> None:
    with SessionLocal() as db:
        db.execute(update(Job).where(*_lease(job_id, attempt, "processing")).values(
            status="failed", error=message[:500], duration_seconds=duration, updated_at=utcnow(),
        ))
        db.commit()


def _safe_metrics(value, depth: int = 0):
    if depth > 5:
        return None
    if isinstance(value, dict):
        return {str(key)[:80]: _safe_metrics(item, depth + 1) for key, item in list(value.items())[:100]}
    if isinstance(value, (tuple, list)):
        return [_safe_metrics(item, depth + 1) for item in value[:500]]
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value if value is None or isinstance(value, (bool, int)) else None


def _output_name(tool: str, sources: list[FileRecord], suffix: str) -> str:
    stem = Path(sources[0].original_filename).stem
    if tool in {"pdf-to-word", "word-to-pdf", "jpg-to-pdf"} and len(sources) == 1:
        return stem + suffix
    return f"{stem}-{tool}{suffix}"


def execute_job(job_id: str, attempt: str, eager_password: str | None = None) -> None:
    if not _claim(job_id, attempt):
        return

    began = time.monotonic()
    pending_key: str | None = None
    tool: str | None = None
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            tool = job.tool
            options = dict(job.settings)
            files = [item.file for item in job.inputs]
            if not all(is_available(record) for record in files):
                raise EngineError("An input upload expired. Upload it again.")
            requires_password = job.requires_password
            config = effective_config(db)

        if requires_password:
            password = eager_password if settings.celery_task_always_eager else take_password(attempt)
            if not password:
                raise EngineError("The password expired. Retry with the document password.")
            options["password"] = password

        with TemporaryDirectory(prefix="job-", dir=work_root()) as temporary:
            directory = Path(temporary)
            sources = []
            for position, record in enumerate(files):
                _progress(job_id, attempt, 2)
                source = directory / f"input-{position}{SOURCE_SUFFIX[record.mime_type]}"
                storage().download(record.storage_key, source)
                sources.append(source)

            suffix = TOOL_OUTPUTS[tool]
            output = directory / f"output{suffix}"

            def report(value: int) -> None:
                _progress(job_id, attempt, value)

            if tool == "pdf-to-word":
                result = convert_pdf(sources[0], output, options, report, max_pages=config.max_pages)
            else:
                result = run_tool(tool, sources, output, options, report, max_pages=config.max_pages)

            _progress(job_id, attempt, 98)
            size_bytes = output.stat().st_size
            if size_bytes == 0:
                raise EngineError("The processor returned an empty file.")
            if size_bytes > settings.max_output_mb * 1024 * 1024:
                raise EngineError("The converted file exceeds the output size limit.")
            mime_type = MIME_TYPES[suffix]
            with SessionLocal() as db:
                pending_key = reserve_object(db, suffix)
            storage().put(pending_key, output, mime_type)

        duration = time.monotonic() - began
        clean = _safe_metrics(result) or {}
        warnings = [str(warning)[:500] for warning in clean.pop("warnings", [])]
        metrics = clean.pop("metrics", {})
        metrics = {**clean, **(metrics if isinstance(metrics, dict) else {})}
        if tool == "ocr-pdf":
            metrics.setdefault("ocr_used", True)
        metrics["duration_seconds"] = round(duration, 3)

        with SessionLocal() as db:
            now = utcnow()
            expiry = now + timedelta(minutes=config.retention_minutes)
            owner = db.execute(
                update(Job).where(*_lease(job_id, attempt, "processing")).values(
                    status="completed",
                    progress=100,
                    duration_seconds=duration,
                    warnings=warnings,
                    metrics=metrics,
                    expires_at=expiry,
                    updated_at=now,
                ).returning(Job.owner_key, Job.user_id, Job.batch_id)
            ).one_or_none()
            if owner is None:
                raise JobStopped()
            output_record = FileRecord(
                id=new_id(),
                owner_key=owner.owner_key,
                user_id=owner.user_id,
                original_filename=_output_name(tool, files, suffix),
                storage_key=pending_key,
                size_bytes=size_bytes,
                page_count=None,
                mime_type=mime_type,
                encrypted=tool == "protect-pdf",
                kind="output",
                expires_at=expiry,
            )
            db.add(output_record)
            db.flush()
            commit_reservation(db, pending_key)
            db.execute(update(Job).where(Job.id == job_id).values(output_file_id=output_record.id))
            if owner.batch_id:
                db.execute(update(Batch).where(Batch.id == owner.batch_id, Batch.expires_at < expiry).values(expires_at=expiry))
            db.commit()
            pending_key = None
        logger.info("conversion_completed", extra={"job_id": job_id, "tool": tool, "duration_seconds": duration})
    except JobStopped:
        logger.info("conversion_stopped", extra={"job_id": job_id, "tool": tool})
    except EngineError as exc:
        _fail(job_id, attempt, str(exc), time.monotonic() - began)
        logger.info("conversion_rejected", extra={"job_id": job_id, "tool": tool})
    except SoftTimeLimitExceeded:
        _fail(job_id, attempt, "Processing exceeded its time limit.", time.monotonic() - began)
        logger.warning("conversion_timed_out", extra={"job_id": job_id, "tool": tool})
    except Exception as exc:
        _fail(job_id, attempt, "The file could not be processed. Retry or try a different setting.", time.monotonic() - began)
        logger.error("conversion_failed", extra={"job_id": job_id, "tool": tool, "error_type": type(exc).__name__})
    finally:
        if pending_key:
            discard_object(pending_key)


@celery_app.task(name="pdfpro.execute")
def conversion_task(job_id: str, attempt: str) -> None:
    execute_job(job_id, attempt)


def publish_task(job_id: str, attempt: str) -> None:
    conversion_task.apply_async(args=(job_id, attempt), task_id=attempt, retry=False)
    try:
        with SessionLocal() as db:
            db.execute(update(Job).where(Job.id == job_id, Job.attempt == attempt).values(dispatched_at=utcnow()))
            db.commit()
    except Exception as exc:
        # The broker has accepted the task. Reconciliation can safely republish
        # if marking this dispatch fails, since the worker claims an attempt once.
        logger.warning("dispatch_mark_deferred", extra={"job_id": job_id, "error_type": type(exc).__name__})


def _recover_unpublished_jobs() -> None:
    now = utcnow()
    stale_before = now - timedelta(seconds=45)
    with SessionLocal() as db:
        jobs = db.execute(select(Job.id, Job.attempt, Job.requires_password).where(
            Job.status == "queued",
            Job.dispatched_at.is_(None),
            Job.deleted_at.is_(None),
            Job.expires_at > now,
            Job.updated_at <= stale_before,
        ).order_by(Job.updated_at).limit(50)).all()

    for job_id, attempt, requires_password in jobs:
        try:
            password_available = not requires_password or has_password(attempt)
            lease = _lease(job_id, attempt, "queued") + (Job.dispatched_at.is_(None), Job.updated_at <= stale_before)
            with SessionLocal() as db:
                changes = {"updated_at": utcnow()}
                if not password_available:
                    changes.update(status="failed", error="The password expired. Retry with the document password.")
                claimed = db.execute(update(Job).where(*lease).values(**changes)).rowcount == 1
                db.commit()
            if claimed and password_available:
                publish_task(job_id, attempt)
        except Exception as exc:
            logger.warning("dispatch_recovery_deferred", extra={"job_id": job_id, "error_type": type(exc).__name__})


@celery_app.task(name="pdfpro.cleanup", ignore_result=True)
def cleanup_task() -> None:
    now = utcnow()
    with SessionLocal() as db:
        db.execute(update(Job).where(
            Job.status.in_(["queued", "processing"]),
            Job.deleted_at.is_(None),
            (Job.expires_at <= now)
            | ((Job.status == "processing") & (Job.updated_at <= now - timedelta(seconds=settings.job_timeout_seconds + 30))),
        ).values(status="failed", error="The job expired or exceeded its processing time limit.", updated_at=now))
        expired = db.scalars(select(FileRecord).where(
            FileRecord.purged_at.is_(None),
            (FileRecord.deleted_at.is_not(None)) | (FileRecord.expires_at <= now),
        ).order_by(FileRecord.expires_at).limit(500)).all()
        purge_files(db, expired)

        cutoff = now - timedelta(days=settings.metadata_retention_days)
        db.execute(delete(Job).where(Job.created_at <= cutoff))
        db.execute(delete(Batch).where(Batch.created_at <= cutoff))
        db.execute(delete(FileRecord).where(
            FileRecord.created_at <= cutoff,
            FileRecord.purged_at.is_not(None),
            ~exists(select(JobInput).where(JobInput.file_id == FileRecord.id)),
            ~exists(select(Job).where(Job.output_file_id == FileRecord.id)),
        ))
        db.execute(delete(UsageBucket).where(UsageBucket.day < (now - timedelta(days=2)).date().isoformat()))
        db.commit()
    if not settings.celery_task_always_eager:
        _recover_unpublished_jobs()
    recover_staged_objects()
    ttl = max(settings.job_timeout_seconds * 2, 7200)
    for directory in (*work_root().glob("job-*"), *work_root().glob("upload-*")):
        try:
            if directory.is_dir() and time.time() - directory.stat().st_mtime > ttl:
                shutil.rmtree(directory)
        except OSError as exc:
            logger.warning("temporary_job_purge_failed", extra={"error_type": type(exc).__name__})
