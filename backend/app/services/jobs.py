import logging
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.security import Identity
from app.engines.pdf_tools import TOOL_OUTPUTS
from app.models import Batch, FileRecord, Job, JobInput, UsageBucket, new_id
from app.schemas import ConfigView, FileView, JobRequest, JobView
from app.services.files import MIME_TYPES, is_available, purge_files
from app.services.job_secrets import forget_password, remember_password
from app.workers.tasks import execute_job, publish_task

logger = logging.getLogger(__name__)
settings = get_settings()
COMBINED_TOOLS = {"merge-pdf", "jpg-to-pdf"}
TERMINAL_STATES = {"completed", "failed", "cancelled"}


def owned_file(db: Session, owner: Identity, file_id: str, *, lock: bool = False) -> FileRecord:
    query = select(FileRecord).where(
        FileRecord.id == file_id,
        FileRecord.owner_key == owner.owner_key,
        FileRecord.kind == "input",
        FileRecord.deleted_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    record = db.scalar(query)
    if record is None:
        raise HTTPException(404, "Upload not found.")
    if not is_available(record):
        raise HTTPException(410, "This upload expired. Upload the file again.")
    return record


def owned_job(db: Session, owner: Identity, job_id: str) -> Job:
    record = db.scalar(select(Job).where(
        Job.id == job_id, Job.owner_key == owner.owner_key, Job.deleted_at.is_(None),
    ))
    if record is None:
        raise HTTPException(404, "Conversion not found.")
    return record


def job_view(job: Job) -> JobView:
    output = job.output
    return JobView(
        id=job.id,
        batch_id=job.batch_id,
        tool=job.tool,
        input_files=[FileView.model_validate(item.file) for item in job.inputs],
        status=job.status,
        progress=job.progress,
        error=job.error,
        warnings=job.warnings,
        metrics=job.metrics,
        created_at=job.created_at,
        expires_at=job.expires_at,
        output_filename=output.original_filename if output and is_available(output) else None,
    )


def _reserve_quota(db: Session, owner: Identity, count: int, limit: int) -> None:
    if count > limit:
        raise HTTPException(429, "Your daily conversion limit has been reached.")
    insert = postgresql_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    query = insert(UsageBucket).values(owner_key=owner.owner_key, day=utcnow().date().isoformat(), count=count)
    query = query.on_conflict_do_update(
        index_elements=[UsageBucket.owner_key, UsageBucket.day],
        set_={"count": UsageBucket.count + count},
        where=(UsageBucket.count + count <= limit),
    ).returning(UsageBucket.count)
    if db.scalar(query) is None:
        raise HTTPException(429, "Your daily conversion limit has been reached.")


def _select_uploads(db: Session, owner: Identity, file_ids: list[str]) -> list[FileRecord]:
    records = db.scalars(select(FileRecord).where(
        FileRecord.id.in_(file_ids),
        FileRecord.owner_key == owner.owner_key,
        FileRecord.kind == "input",
        FileRecord.deleted_at.is_(None),
    ).order_by(FileRecord.id).with_for_update()).all()
    if len(records) != len(file_ids):
        raise HTTPException(404, "One or more selected uploads could not be found.")
    if not all(is_available(record) for record in records):
        raise HTTPException(410, "One or more selected uploads expired. Upload them again.")
    by_id = {record.id: record for record in records}
    return [by_id[file_id] for file_id in file_ids]


def _validate_options(request: JobRequest, files: list[FileRecord], config: ConfigView, batch: bool) -> None:
    tool = request.tool
    options = request.settings
    if tool not in TOOL_OUTPUTS:
        raise HTTPException(422, "Select a supported document tool.")
    if len(files) > config.max_batch_files:
        raise HTTPException(413, f"Select up to {config.max_batch_files} files per request.")
    if batch and tool in COMBINED_TOOLS:
        raise HTTPException(422, "Create one combined job for this tool.")
    if not batch and tool not in COMBINED_TOOLS and len(files) != 1:
        raise HTTPException(422, "Select one input or start a batch of independent jobs.")
    if tool == "merge-pdf" and len(files) < 2:
        raise HTTPException(422, "Select at least two PDF files to merge.")
    extension = {"word-to-pdf": ".docx", "jpg-to-pdf": ".jpg"}.get(tool, ".pdf")
    if not all(record.mime_type == MIME_TYPES[extension] for record in files):
        raise HTTPException(422, f"Select a file of type {extension[1:].upper()} for this tool.")
    if tool != "unlock-pdf" and any(record.encrypted for record in files):
        raise HTTPException(422, "This PDF is password protected. Unlock it with its password before processing.")
    if tool in {"protect-pdf", "unlock-pdf"} and not options.password:
        raise HTTPException(422, "Enter the PDF password.")
    if tool == "protect-pdf" and (len(options.password) < 8 or len(options.password.encode()) > 32):
        raise HTTPException(422, "Use a password of at least 8 characters and at most 32 UTF-8 bytes.")
    if tool not in {"protect-pdf", "unlock-pdf"} and options.password:
        raise HTTPException(422, "Passwords are accepted by the Protect PDF and Unlock PDF tools.")
    if tool == "ocr-pdf" and options.ocr == "off":
        raise HTTPException(422, "Choose automatic or forced OCR for OCR PDF.")
    if (tool == "ocr-pdf" or (tool == "pdf-to-word" and options.ocr != "off" and options.mode != "visual")):
        unsupported = sorted(set(options.languages) - set(config.ocr_languages))
        if unsupported:
            raise HTTPException(422, f"OCR languages are disabled: {', '.join(unsupported)}.")
    if tool == "watermark-pdf" and not (options.text and options.text.strip()):
        raise HTTPException(422, "Enter the watermark text.")
    if tool in {"extract-pages", "delete-pages"} and not options.pages:
        raise HTTPException(422, "Select the pages to process.")


def _clear_secret(attempt: str) -> None:
    try:
        forget_password(attempt)
    except Exception as exc:
        logger.warning("job_password_cleanup_deferred", extra={"error_type": type(exc).__name__})


def _enqueue(db: Session, job: Job, password: str | None) -> Job:
    try:
        if settings.celery_task_always_eager:
            execute_job(job.id, job.attempt, password)
        else:
            if password:
                remember_password(job.attempt, password, int((job.expires_at - utcnow()).total_seconds()))
            publish_task(job.id, job.attempt)
    except Exception as exc:
        db.execute(update(Job).where(Job.id == job.id, Job.attempt == job.attempt, Job.status == "queued").values(
            status="failed", error="The processing queue is unavailable. Retry the conversion.", updated_at=utcnow(),
        ))
        db.commit()
        _clear_secret(job.attempt)
        logger.error("queue_publish_failed", extra={"job_id": job.id, "error_type": type(exc).__name__})
    db.refresh(job)
    return job


def create_jobs(
    db: Session, owner: Identity, request: JobRequest, config: ConfigView, *, batch: bool = False,
) -> tuple[list[Job], str | None]:
    files = _select_uploads(db, owner, [str(file_id) for file_id in request.file_ids])
    _validate_options(request, files, config, batch)
    _reserve_quota(db, owner, len(files) if batch else 1, config.daily_conversion_limit)
    expiry = utcnow() + timedelta(minutes=config.retention_minutes)
    batch_id = None
    if batch:
        batch_id = new_id()
        db.add(Batch(id=batch_id, owner_key=owner.owner_key, user_id=owner.user_id, expires_at=expiry))
        db.flush()
    groups = [[record] for record in files] if batch else [files]
    options = request.settings.model_dump(exclude={"password"}, exclude_none=True)
    password = request.settings.password
    jobs = [
        Job(
            id=new_id(),
            owner_key=owner.owner_key,
            user_id=owner.user_id,
            batch_id=batch_id,
            tool=request.tool,
            settings=options,
            requires_password=bool(password),
            expires_at=expiry,
            inputs=[JobInput(position=index, file_id=record.id) for index, record in enumerate(group)],
        )
        for group in groups
    ]
    db.add_all(jobs)
    db.commit()
    return [_enqueue(db, job, password) for job in jobs], batch_id


def retry_job(db: Session, owner: Identity, job: Job, password: str | None, config: ConfigView) -> Job:
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(409, "Only failed or cancelled jobs can be retried.")
    if job.requires_password and not password:
        raise HTTPException(422, "Enter the PDF password to retry.")
    if job.tool == "protect-pdf" and (len(password) < 8 or len(password.encode()) > 32):
        raise HTTPException(422, "Use a password of at least 8 characters and at most 32 UTF-8 bytes.")
    files = _select_uploads(db, owner, [item.file_id for item in job.inputs])
    if not files:
        raise HTTPException(410, "The source files expired. Upload them again.")
    _reserve_quota(db, owner, 1, config.daily_conversion_limit)
    now = utcnow()
    result = db.execute(update(Job).where(
        Job.id == job.id,
        Job.attempt == job.attempt,
        Job.status.in_(["failed", "cancelled"]),
        Job.deleted_at.is_(None),
    ).values(
        status="queued", progress=0, error=None, warnings=[], metrics={}, duration_seconds=None,
        attempt=new_id(), dispatched_at=None, updated_at=now, expires_at=now + timedelta(minutes=config.retention_minutes),
    ))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "The job changed while it was being retried.")
    db.commit()
    db.refresh(job)
    return _enqueue(db, job, password if job.requires_password else None)


def cancel_job(db: Session, job: Job) -> Job:
    result = db.execute(update(Job).where(
        Job.id == job.id, Job.attempt == job.attempt, Job.status.in_(["queued", "processing"]),
        Job.deleted_at.is_(None),
    ).values(status="cancelled", error=None, updated_at=utcnow()))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Only queued or processing jobs can be cancelled.")
    db.commit()
    if job.requires_password:
        _clear_secret(job.attempt)
    db.refresh(job)
    return job


def delete_job(db: Session, job: Job) -> None:
    now = utcnow()
    sources = [item.file_id for item in job.inputs]
    db.scalars(select(FileRecord).where(FileRecord.id.in_(sources)).order_by(FileRecord.id).with_for_update()).all()
    result = db.execute(update(Job).where(
        Job.id == job.id, Job.deleted_at.is_(None),
    ).values(deleted_at=now, updated_at=now).returning(Job.output_file_id, Job.attempt, Job.requires_password)).one_or_none()
    if result is None:
        raise HTTPException(404, "Conversion not found.")
    inputs = db.scalars(select(FileRecord).where(
        FileRecord.id.in_(sources),
        ~exists(select(JobInput).join(Job, Job.id == JobInput.job_id).where(
            JobInput.file_id == FileRecord.id, Job.deleted_at.is_(None),
        )),
    )).all()
    if result.output_file_id:
        output = db.get(FileRecord, result.output_file_id)
        if output is not None:
            inputs.append(output)
    for record in inputs:
        record.deleted_at = now
    db.commit()
    if result.requires_password:
        _clear_secret(result.attempt)
    if not purge_files(db, inputs):
        raise HTTPException(503, "Access has been removed. Storage deletion will retry automatically.")
