import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, utcnow
from app.models import FileRecord, StagedObject
from app.services.storage import object_key, storage

logger = logging.getLogger(__name__)
# Reservation happens after rendering or upload parsing, just before writing.
# Reclaim interrupted writes in time for the default 60-minute retention.
STAGING_GRACE = timedelta(minutes=55)


def reserve_object(db: Session, suffix: str) -> str:
    key = object_key(suffix)
    db.add(StagedObject(storage_key=key))
    db.commit()
    return key


def commit_reservation(db: Session, key: str) -> None:
    result = db.execute(delete(StagedObject).where(StagedObject.storage_key == key))
    if result.rowcount != 1:
        raise RuntimeError("The storage reservation is no longer active.")


def discard_object(key: str) -> None:
    try:
        with SessionLocal() as db:
            # In an ambiguous database commit, a completed registration already
            # removed its reservation and must keep its object.
            reservation = db.scalar(select(StagedObject).where(
                StagedObject.storage_key == key,
            ).with_for_update())
            if reservation is None and db.scalar(select(FileRecord.id).where(FileRecord.storage_key == key)):
                return
            storage().delete(key)
            if reservation is not None:
                db.delete(reservation)
            db.commit()
    except Exception as exc:
        logger.error("staged_object_cleanup_deferred", extra={"error_type": type(exc).__name__})


def recover_staged_objects() -> None:
    with SessionLocal() as db:
        keys = db.scalars(select(StagedObject.storage_key).where(
            StagedObject.created_at <= utcnow() - STAGING_GRACE,
        ).order_by(StagedObject.created_at).limit(50)).all()
    for key in keys:
        discard_object(key)
