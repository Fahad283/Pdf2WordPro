import asyncio
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db, utcnow
from app.core.rate_limit import throttle
from app.core.security import Identity, get_identity
from app.models import Batch, Job
from app.schemas import BatchView, JobRequest, JobView, RetryRequest
from app.services.delivery import attachment, download_record, stream_archive
from app.services.files import is_available
from app.services.jobs import (
    TERMINAL_STATES, cancel_job, create_jobs, delete_job, job_view, owned_job, retry_job,
)
from app.services.settings import effective_config

router = APIRouter(prefix="/conversions", tags=["conversions"])


@router.post("", response_model=JobView, status_code=202)
def submit_job(
    request: Request,
    payload: JobRequest,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> JobView:
    throttle(request, "job-ip", 180)
    throttle(request, "job-owner", 60, identity.owner_key)
    jobs, _ = create_jobs(db, identity, payload, effective_config(db))
    return job_view(jobs[0])


@router.post("/batch", response_model=BatchView, status_code=202)
def submit_batch(
    request: Request,
    payload: JobRequest,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> BatchView:
    throttle(request, "job-ip", 180)
    throttle(request, "job-owner", 60, identity.owner_key)
    jobs, batch_id = create_jobs(db, identity, payload, effective_config(db), batch=True)
    return BatchView(id=batch_id, jobs=[job_view(job) for job in jobs])


@router.get("/history")
def history(
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> dict[str, list[JobView]]:
    jobs = db.scalars(select(Job).where(
        Job.owner_key == identity.owner_key,
        Job.deleted_at.is_(None),
    ).order_by(Job.created_at.desc()).limit(100)).all()
    return {"jobs": [job_view(job) for job in jobs]}


@router.get("/batches/{batch_id}/download")
def batch_download(
    batch_id: UUID,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    batch = db.scalar(select(Batch).where(Batch.id == str(batch_id), Batch.owner_key == identity.owner_key))
    if batch is None:
        raise HTTPException(404, "Batch not found.")
    if batch.expires_at <= utcnow():
        raise HTTPException(410, "This batch expired.")
    jobs = db.scalars(select(Job).where(
        Job.batch_id == batch.id,
        Job.owner_key == identity.owner_key,
        Job.status == "completed",
        Job.deleted_at.is_(None),
    ).order_by(Job.created_at, Job.id)).all()
    outputs = [job.output for job in jobs if job.output and is_available(job.output)]
    if not outputs:
        raise HTTPException(409, "There are no available results in this batch yet.")
    return StreamingResponse(
        stream_archive(outputs),
        media_type="application/zip",
        headers={"Content-Disposition": attachment("pdf-to-word-pro-results.zip")},
    )


@router.get("/{job_id}", response_model=JobView)
def status(
    job_id: UUID,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> JobView:
    return job_view(owned_job(db, identity, str(job_id)))


def _snapshot(identity: Identity, job_id: str) -> JobView:
    with SessionLocal() as db:
        return job_view(owned_job(db, identity, job_id))


@router.get("/{job_id}/events")
async def events(
    job_id: UUID,
    request: Request,
    identity: Identity = Depends(get_identity),
) -> StreamingResponse:
    await asyncio.to_thread(throttle, request, "events", 120, identity.owner_key)
    key = str(job_id)
    initial = await asyncio.to_thread(_snapshot, identity, key)

    async def updates():
        previous = None
        last_message = 0.0
        start = time.monotonic()
        current = initial
        yield "retry: 2000\n\n"
        while not await request.is_disconnected() and time.monotonic() - start < 1200:
            data = current.model_dump_json()
            if data != previous:
                yield f"event: status\ndata: {data}\n\n"
                last_message = time.monotonic()
                previous = data
            elif time.monotonic() - last_message >= 12:
                yield ": heartbeat\n\n"
                last_message = time.monotonic()
            if current.status in TERMINAL_STATES:
                return
            await asyncio.sleep(1)
            try:
                current = await asyncio.to_thread(_snapshot, identity, key)
            except HTTPException:
                return

    return StreamingResponse(
        updates(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/{job_id}/download")
def download(
    job_id: UUID,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    job = owned_job(db, identity, str(job_id))
    if job.status != "completed":
        raise HTTPException(409, "This conversion has no result ready to download.")
    if job.output is None or not is_available(job.output):
        raise HTTPException(410, "The result expired or was removed.")
    return download_record(job.output)


@router.post("/{job_id}/retry", response_model=JobView, status_code=202)
def retry(
    job_id: UUID,
    request: Request,
    payload: RetryRequest | None = None,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> JobView:
    throttle(request, "job-ip", 180)
    throttle(request, "job-owner", 60, identity.owner_key)
    job = owned_job(db, identity, str(job_id))
    return job_view(retry_job(db, identity, job, payload.password if payload else None, effective_config(db)))


@router.post("/{job_id}/cancel", response_model=JobView)
def cancel(
    job_id: UUID,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> JobView:
    return job_view(cancel_job(db, owned_job(db, identity, str(job_id))))


@router.delete("/{job_id}", status_code=204)
def remove(
    job_id: UUID,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> Response:
    delete_job(db, owned_job(db, identity, str(job_id)))
    return Response(status_code=204)
