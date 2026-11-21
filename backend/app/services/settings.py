from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AdminSetting
from app.schemas import ConfigView


def effective_config(db: Session) -> ConfigView:
    settings = get_settings()
    values = {
        "max_upload_mb": settings.max_upload_mb,
        "max_pages": settings.max_pages,
        "max_batch_files": settings.max_batch_files,
        "retention_minutes": settings.retention_minutes,
        "ocr_languages": settings.configured_languages,
        "daily_conversion_limit": settings.daily_conversion_limit,
    }
    values.update((entry.key, entry.value) for entry in db.scalars(select(AdminSetting)) if entry.key in values)
    return ConfigView.model_validate(values)


def write_config(db: Session, updates: dict) -> ConfigView:
    for key, value in updates.items():
        if key == "ocr_languages":
            value = list(dict.fromkeys(value))
        db.merge(AdminSetting(key=key, value=value))
    db.commit()
    return effective_config(db)
