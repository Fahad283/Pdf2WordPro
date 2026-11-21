"""Store immutable benchmark inputs and bounded diagnostic artifacts."""

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import StagedObject
from app.services.staging import commit_reservation, discard_object
from app.services.storage import object_key, storage

from .configuration import ASSET_TYPES


def checksum(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while part := stream.read(1024 * 1024):
            digest.update(part)
    return digest.hexdigest()


@contextmanager
def staged_assets(assets: dict[str, Path]):
    keys = {label: object_key(path.suffix) for label, path in assets.items()}
    with SessionLocal() as db:
        db.add_all(StagedObject(storage_key=key) for key in keys.values())
        db.commit()
    try:
        for label, path in assets.items():
            storage().put(keys[label], path, ASSET_TYPES[path.suffix])
        yield keys
    finally:
        with SessionLocal() as db:
            pending = list(db.scalars(select(StagedObject.storage_key).where(
                StagedObject.storage_key.in_(keys.values())
            ))) if keys else []
        for key in pending:
            discard_object(key)


def publish_assets(db, keys: dict[str, str]) -> None:
    for key in keys.values():
        commit_reservation(db, key)
