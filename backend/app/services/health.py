from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.rate_limit import redis_client
from app.services.malware import scanner_health
from app.services.storage import storage


def checks() -> dict[str, str]:
    settings = get_settings()
    statuses = {"database": "unavailable", "redis": "unavailable", "storage": "unavailable"}
    try:
        with SessionLocal() as db:
            # Query a migrated table so an empty, reachable data store is not considered ready.
            db.execute(text("SELECT 1 FROM users LIMIT 1"))
        statuses["database"] = "ok"
    except Exception:
        pass
    try:
        if settings.celery_task_always_eager:
            statuses["redis"] = "eager"
        elif redis_client.ping():
            statuses["redis"] = "ok"
    except Exception:
        pass
    try:
        if storage().healthy():
            statuses["storage"] = "ok"
    except Exception:
        pass
    statuses["malware_scanner"] = scanner_health()
    return statuses


def healthy(statuses: dict[str, str]) -> bool:
    return (
        all(statuses.get(check) in {"ok", "eager"} for check in ("database", "redis", "storage"))
        and (not get_settings().clamav_required or statuses["malware_scanner"] == "ok")
    )
