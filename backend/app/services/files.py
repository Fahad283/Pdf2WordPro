import logging
import re
import unicodedata
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

import pymupdf
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.models import FileRecord
from app.services.storage import storage

logger = logging.getLogger(__name__)
MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpg": "image/jpeg",
    ".zip": "application/zip",
}


def safe_filename(name: str | None) -> str:
    basename = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    basename = unicodedata.normalize("NFC", basename)
    basename = "".join(char for char in basename if unicodedata.category(char)[0] != "C")
    basename = re.sub(r'[<>:"/\\|?*]', "_", basename).strip(" .")
    if not basename:
        raise HTTPException(422, "Provide a filename with a supported extension.")
    suffix = Path(basename).suffix[:12]
    # Keep attachment/ZIP filenames within common filesystem byte limits as well.
    stem = basename[:-len(suffix)] if suffix else basename
    stem = stem.encode("utf-8")[:220].decode("utf-8", errors="ignore").rstrip(" .")
    return stem + suffix


def _check_pdf(path: Path, max_pages: int) -> tuple[int | None, bool]:
    try:
        with pymupdf.open(path, filetype="pdf") as document:
            if document.is_repaired or not document.is_pdf or document.page_count < 1:
                raise HTTPException(422, "The PDF is damaged or does not contain any pages.")
            if document.needs_pass:
                return None, True
            if document.page_count > max_pages:
                raise HTTPException(413, f"PDFs can contain up to {max_pages} pages.")
            return document.page_count, False
    except (RuntimeError, ValueError):
        raise HTTPException(422, "The PDF is damaged or unsupported.") from None


def _check_docx(path: Path) -> None:
    try:
        with ZipFile(path) as package:
            entries = package.infolist()
            names = {entry.filename for entry in entries}
            if len(entries) > 10000 or len(entries) != len(names):
                raise HTTPException(422, "The Word archive contains too many or duplicate parts.")
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
                raise HTTPException(422, "The upload is not a standard DOCX document.")
            if sum(entry.file_size for entry in entries) > 256 * 1024 * 1024:
                raise HTTPException(413, "The expanded Word document exceeds the processing limit.")
            for entry in entries:
                name = entry.filename
                lower = name.lower()
                if ("\\" in name or "\x00" in name or name.startswith("/") or ":" in name
                        or ".." in PurePosixPath(name).parts or entry.flag_bits & 1
                        or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                    raise HTTPException(422, "The Word archive contains an unsafe file entry.")
                if ("/embeddings/" in lower or "/activex/" in lower or "vbaproject" in lower
                        or lower.endswith((".exe", ".dll", ".bin", ".docm"))):
                    raise HTTPException(422, "Word documents with macros or embedded files are unsupported.")
    except (BadZipFile, OSError):
        raise HTTPException(422, "The Word document archive is damaged.") from None


def inspect_upload(path: Path, name: str, max_pages: int) -> tuple[str, int | None, bool]:
    suffix = Path(name).suffix.lower()
    with path.open("rb") as source:
        magic = source.read(8)
    if suffix == ".pdf" and re.fullmatch(rb"%PDF-[12]\.[0-9]", magic):
        pages, encrypted = _check_pdf(path, max_pages)
        return MIME_TYPES[".pdf"], pages, encrypted
    if suffix == ".docx" and magic.startswith(b"PK\x03\x04"):
        _check_docx(path)
        return MIME_TYPES[".docx"], None, False
    if suffix in {".jpeg", ".jpg"} and magic.startswith(b"\xff\xd8\xff"):
        try:
            with Image.open(path, formats=["JPEG"]) as image:
                if image.width * image.height > 40_000_000:
                    raise HTTPException(413, "JPEG images can contain up to 40 megapixels.")
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
            raise HTTPException(422, "The JPEG is damaged or unsupported.") from None
        return MIME_TYPES[".jpg"], None, False
    raise HTTPException(422, "Use a valid PDF, DOCX, or JPEG file with the matching extension.")


def is_available(record: FileRecord) -> bool:
    return record.deleted_at is None and record.expires_at > utcnow()


def purge_files(db: Session, records: list[FileRecord]) -> bool:
    failed = False
    for record in records:
        if record.purged_at is not None:
            continue
        try:
            storage().delete(record.storage_key)
            record.purged_at = utcnow()
        except Exception as exc:
            logger.error("object_purge_failed", extra={"error_type": type(exc).__name__})
            failed = True
    db.commit()
    return not failed


def work_root() -> Path:
    path = get_settings().work_dir.resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path
