from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.models import FileRecord
from app.services.storage import storage, stream_file


def attachment(name: str) -> str:
    safe_ascii = name.encode("ascii", "ignore").decode("ascii").replace('"', "_")
    if not safe_ascii or safe_ascii.startswith("."):
        safe_ascii = "document" + Path(name).suffix
    return f"attachment; filename=\"{safe_ascii}\"; filename*=UTF-8''{quote(name, safe='')}"


def download_record(record: FileRecord) -> StreamingResponse:
    try:
        reader = storage().open(record.storage_key)
    except Exception:
        raise HTTPException(503, "The stored file is temporarily unavailable.") from None
    return StreamingResponse(
        stream_file(reader),
        media_type=record.mime_type,
        headers={
            "Content-Disposition": attachment(record.original_filename),
            "Content-Length": str(record.size_bytes),
        },
    )


class ZipTarget:
    def __init__(self):
        self.chunks: list[bytes] = []

    def write(self, data: bytes) -> int:
        if data:
            self.chunks.append(data)
        return len(data)

    def flush(self) -> None:
        pass

    def drain(self) -> Iterator[bytes]:
        chunks, self.chunks = self.chunks, []
        yield from chunks


def stream_archive(outputs: list[FileRecord]) -> Iterator[bytes]:
    names: set[str] = set()
    target = ZipTarget()
    with ZipFile(target, "w", compression=ZIP_STORED) as archive:
        for output in outputs:
            name = output.original_filename
            candidate = name
            number = 2
            while candidate.casefold() in names:
                filename = Path(name)
                candidate = f"{filename.stem} ({number}){filename.suffix}"
                number += 1
            names.add(candidate.casefold())
            entry = ZipInfo(candidate)
            entry.file_size = output.size_bytes
            with storage().open(output.storage_key) as reader, archive.open(entry, "w", force_zip64=True) as writer:
                yield from target.drain()
                while chunk := reader.read(1024 * 256):
                    writer.write(chunk)
                    yield from target.drain()
            yield from target.drain()
    yield from target.drain()
