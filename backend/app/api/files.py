import shutil
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.database import get_db, utcnow
from app.core.rate_limit import throttle
from app.core.security import Identity, get_identity
from app.models import FileRecord, Job, JobInput
from app.schemas import FileView
from app.services.files import inspect_upload, purge_files, safe_filename, work_root
from app.services.jobs import owned_file
from app.services.malware import scan_file
from app.services.settings import effective_config
from app.services.staging import commit_reservation, discard_object, reserve_object
from app.services.storage import storage

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload", response_model=FileView, status_code=201)
def upload(
    request: Request,
    file: UploadFile = File(...),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> FileView:
    throttle(request, "upload-owner", 40, identity.owner_key)
    config = effective_config(db)
    name = safe_filename(file.filename)
    suffix = Path(name).suffix.lower()
    if suffix == ".jpeg":
        suffix = ".jpg"
    if suffix not in {".pdf", ".docx", ".jpg"}:
        raise HTTPException(422, "Use a PDF, DOCX, or JPEG file.")
    limit = config.max_upload_mb * 1024 * 1024
    if file.size is not None and file.size > limit:
        raise HTTPException(413, f"Each upload can be up to {config.max_upload_mb} MB.")

    with TemporaryDirectory(prefix="upload-", dir=work_root()) as temporary:
        staged = Path(temporary) / f"upload{suffix}"
        size = 0
        with staged.open("xb") as destination:
            while chunk := file.file.read(1024 * 256):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Each upload can be up to {config.max_upload_mb} MB.")
                destination.write(chunk)
        if size == 0:
            raise HTTPException(422, "The uploaded file is empty.")
        scan_file(staged)
        mime_type, page_count, encrypted = inspect_upload(staged, name, config.max_pages)
        key = reserve_object(db, suffix)
        record = FileRecord(
            owner_key=identity.owner_key,
            user_id=identity.user_id,
            original_filename=name,
            storage_key=key,
            size_bytes=size,
            page_count=page_count,
            mime_type=mime_type,
            encrypted=encrypted,
            expires_at=utcnow() + timedelta(minutes=config.retention_minutes),
        )
        try:
            storage().put(key, staged, mime_type)
            db.add(record)
            commit_reservation(db, key)
            db.commit()
        except Exception:
            db.rollback()
            discard_object(key)
            raise
    return FileView.model_validate(record)


@router.delete("/{file_id}", status_code=204)
def delete_upload(
    file_id: UUID,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> Response:
    record = owned_file(db, identity, str(file_id), lock=True)
    in_use = db.scalar(select(exists().where(
        JobInput.file_id == record.id,
        JobInput.job_id == Job.id,
        Job.deleted_at.is_(None),
        Job.status.in_(["queued", "processing"]),
    )))
    if in_use:
        raise HTTPException(409, "Cancel active conversions before deleting this upload.")
    record.deleted_at = utcnow()
    db.commit()
    if not purge_files(db, [record]):
        raise HTTPException(503, "Access has been removed. Storage deletion will retry automatically.")
    return Response(status_code=204)
