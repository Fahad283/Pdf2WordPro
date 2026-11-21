from datetime import UTC
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import redis_client
from app.core.security import require_admin
from app.models import FileRecord, Job, User
from app.schemas import ConfigPatch, ConfigView, UserPatch, UserView
from app.services.health import checks, healthy
from app.services.settings import effective_config, write_config

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)) -> dict:
    health = checks()
    if get_settings().celery_task_always_eager:
        queue_status = "development"
    else:
        try:
            pending = redis_client.llen("pdfpro")
            queue_status = f"{pending} queued" if pending else "Ready"
        except RedisError:
            queue_status = "Unavailable"
    counts = dict(db.execute(
        select(Job.status, func.count(Job.id)).where(Job.deleted_at.is_(None)).group_by(Job.status)
    ).all())
    jobs = db.scalars(select(Job).where(
        Job.status == "failed", Job.error.is_not(None), Job.deleted_at.is_(None)
    ).order_by(Job.updated_at.desc()).limit(10)).all()
    return {
        "total_users": db.scalar(select(func.count(User.id))),
        "total_uploads": db.scalar(select(func.count(FileRecord.id)).where(FileRecord.kind == "input")),
        "total_conversions": sum(counts.values()),
        "successful_conversions": counts.get("completed", 0),
        "failed_conversions": counts.get("failed", 0),
        "active_jobs": counts.get("queued", 0) + counts.get("processing", 0),
        "queue_status": queue_status,
        "average_conversion_seconds": round(db.scalar(select(func.avg(Job.duration_seconds)).where(
            Job.status == "completed", Job.deleted_at.is_(None),
        )) or 0, 2),
        "storage_bytes": db.scalar(select(func.coalesce(func.sum(FileRecord.size_bytes), 0)).where(
            FileRecord.purged_at.is_(None),
        )),
        "ocr_jobs": db.scalar(select(func.count(Job.id)).where(
            Job.metrics["ocr_used"].as_boolean().is_(True), Job.deleted_at.is_(None),
        )),
        "system_health": "Healthy" if healthy(health) else "Degraded",
        "recent_errors": [
            {"id": job.id, "tool": job.tool, "error": job.error, "created_at": job.created_at.replace(tzinfo=UTC)}
            for job in jobs
        ],
    }


@router.get("/settings", response_model=ConfigView)
def settings(db: Session = Depends(get_db)) -> ConfigView:
    return effective_config(db)


@router.patch("/settings", response_model=ConfigView)
def update_settings(payload: ConfigPatch, db: Session = Depends(get_db)) -> ConfigView:
    values = payload.model_dump(exclude_unset=True, exclude_none=True)
    return write_config(db, values)


@router.get("/users")
def users(db: Session = Depends(get_db)) -> dict[str, list[UserView]]:
    records = db.scalars(select(User).order_by(User.created_at.desc()).limit(100)).all()
    return {"users": [UserView.model_validate(record) for record in records]}


@router.patch("/users/{user_id}", response_model=UserView)
def update_user(
    user_id: UUID,
    payload: UserPatch,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, str(user_id))
    if user is None:
        raise HTTPException(404, "Account not found.")
    if payload.status and payload.status != user.status:
        if admin.id == user.id or user.role == "admin":
            raise HTTPException(409, "Administrator accounts cannot be suspended from this dashboard.")
        user.status = payload.status
        user.session_version += 1
    if payload.plan:
        user.plan = payload.plan
    db.commit()
    return user
