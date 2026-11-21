"""Small defensive checks on the same local validation and storage interfaces."""

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from fastapi import HTTPException

from app.engines import EngineError, open_pdf
from app.engines.pdf_tools import validate_docx
from app.services.files import inspect_upload, safe_filename
from app.services.storage import LocalStorage


@contextmanager
def _expect(error: type[Exception]):
    try:
        yield
    except error:
        return
    raise AssertionError("Invalid input was accepted.")


def run_checks() -> list[dict]:
    results = []

    def check(key, title, operation):
        try:
            operation()
        except Exception as exc:
            results.append({"id": key, "name": title, "passed": False, "detail": type(exc).__name__})
        else:
            results.append({"id": key, "name": title, "passed": True, "detail": "Verified against the active implementation."})

    with TemporaryDirectory(prefix="bench-check-") as directory:
        base = Path(directory)
        sample = base / "invalid.pdf"
        sample.write_bytes(b"PDF document marker is absent.")
        report = base / "invalid.docx"
        with ZipFile(report, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types />")
            archive.writestr("word/document.xml", "<document />")
            archive.writestr("../unexpected-content", "synthetic fixture")
        objects = LocalStorage(base / "objects")

        def signatures():
            with _expect(HTTPException):
                inspect_upload(sample, "normal.pdf", 10)
            with _expect(EngineError):
                open_pdf(sample, max_pages=10)

        def package():
            with _expect(EngineError):
                validate_docx(report)

        def filenames():
            assert safe_filename("../../original.pdf") == "original.pdf"
            assert safe_filename("folder\\report.pdf") == "report.pdf"

        def keys():
            with _expect(ValueError):
                objects.open("../invalid.pdf")

        def cleanup():
            with TemporaryDirectory(dir=base) as ephemeral:
                path = Path(ephemeral)
                (path / "source").write_bytes(b"generated test")
            assert not path.exists()

        check("signature", "File signatures and malformed PDF rejection", signatures)
        check("archive", "Unsafe DOCX archive entries", package)
        check("filenames", "Untrusted filename normalization", filenames)
        check("object-keys", "Private storage key isolation", keys)
        check("temporary-cleanup", "Temporary workspace cleanup", cleanup)
    return results
