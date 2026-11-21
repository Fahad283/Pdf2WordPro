from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import throttle
from app.core.security import Identity, get_identity
from app.schemas import InspectRequest, JobRequest, JobView, OCRRequest
from app.services.files import MIME_TYPES
from app.services.jobs import create_jobs, job_view, owned_file
from app.services.settings import effective_config

router = APIRouter(prefix="/pdf", tags=["pdf"])


@router.post("/inspect")
def inspect(
    payload: InspectRequest,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> dict:
    record = owned_file(db, identity, str(payload.file_id))
    if record.mime_type != MIME_TYPES[".pdf"]:
        raise HTTPException(422, "Select a PDF to inspect.")
    return {
        "file_id": record.id,
        "page_count": record.page_count,
        "encrypted": record.encrypted,
        "size_bytes": record.size_bytes,
        "mime_type": record.mime_type,
        "requires_ocr_analysis": not record.encrypted,
    }


@router.post("/ocr", response_model=JobView, status_code=202)
def ocr(
    payload: OCRRequest,
    request: Request,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> JobView:
    throttle(request, "job-ip", 180)
    throttle(request, "job-owner", 60, identity.owner_key)
    job_request = JobRequest(tool="ocr-pdf", file_ids=[payload.file_id], settings=payload.settings)
    jobs, _ = create_jobs(db, identity, job_request, effective_config(db))
    return job_view(jobs[0])
