import os
import re
import shutil
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app.core.config import get_settings

KEY_PATTERN = re.compile(r"^[a-f0-9]{32}\.[a-z0-9]{2,8}$")


def object_key(suffix: str) -> str:
    key = uuid4().hex + suffix
    if not KEY_PATTERN.fullmatch(key):
        raise ValueError("Invalid object key extension.")
    return key


def _validate_key(key: str) -> None:
    if not KEY_PATTERN.fullmatch(key):
        raise ValueError("Invalid object key.")


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, key: str) -> Path:
        _validate_key(key)
        return self.root / key

    def put(self, key: str, source: Path, mime_type: str) -> None:
        destination = self._path(key)
        pending = self.root / f".{key}.tmp"
        try:
            with source.open("rb") as reader, pending.open("xb") as writer:
                os.chmod(pending, 0o600)
                shutil.copyfileobj(reader, writer)
            pending.replace(destination)
        finally:
            pending.unlink(missing_ok=True)

    def download(self, key: str, destination: Path) -> None:
        shutil.copyfile(self._path(key), destination)

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        (self.root / f".{key}.tmp").unlink(missing_ok=True)

    def healthy(self) -> bool:
        return self.root.is_dir() and os.access(self.root, os.R_OK | os.W_OK | os.X_OK)


class S3Storage:
    def __init__(self):
        import boto3
        from botocore.config import Config

        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
            config=Config(connect_timeout=3, read_timeout=20, retries={"max_attempts": 2}),
        )

    def put(self, key: str, source: Path, mime_type: str) -> None:
        _validate_key(key)
        with source.open("rb") as reader:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=reader, ContentType=mime_type)

    def download(self, key: str, destination: Path) -> None:
        with self.open(key) as reader, destination.open("wb") as writer:
            shutil.copyfileobj(reader, writer)

    def open(self, key: str) -> BinaryIO:
        _validate_key(key)
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]

    def delete(self, key: str) -> None:
        _validate_key(key)
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def healthy(self) -> bool:
        self.client.head_bucket(Bucket=self.bucket)
        return True


@lru_cache
def storage() -> LocalStorage | S3Storage:
    settings = get_settings()
    return S3Storage() if settings.storage_backend == "s3" else LocalStorage(settings.storage_dir)


def stream_file(reader: BinaryIO) -> Iterator[bytes]:
    with reader:
        while chunk := reader.read(1024 * 256):
            yield chunk
