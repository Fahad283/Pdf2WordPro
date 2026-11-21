"""Additional PDF operations executed in the document worker."""

from __future__ import annotations

from io import BytesIO
from html import escape
from pathlib import Path, PurePosixPath
import json
import secrets
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile
from xml.etree import ElementTree

import pymupdf as fitz
from PIL import Image, ImageOps, UnidentifiedImageError

from app.engines import EngineError, open_pdf, select_pages
from app.engines.ocr import check_ocr_languages
from app.engines.process_env import processor_environment

TOOL_OUTPUTS = {
    "pdf-to-word": ".docx",
    "word-to-pdf": ".pdf",
    "merge-pdf": ".pdf",
    "split-pdf": ".zip",
    "compress-pdf": ".pdf",
    "rotate-pdf": ".pdf",
    "extract-pages": ".pdf",
    "delete-pages": ".pdf",
    "pdf-to-jpg": ".zip",
    "jpg-to-pdf": ".pdf",
    "ocr-pdf": ".pdf",
    "watermark-pdf": ".pdf",
    "page-numbers": ".pdf",
    "protect-pdf": ".pdf",
    "unlock-pdf": ".pdf",
}

Progress = Callable[[int], None]
MAX_IMAGE_PIXELS = 40_000_000
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 12_000


def _run_command(command: list[str], name: str, directory: Path, timeout: int) -> None:
    try:
        result = subprocess.run(
            command, cwd=directory, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout, check=False, env=processor_environment(directory),
        )
    except FileNotFoundError as exc:
        raise EngineError(f"{name} is unavailable on this worker. Contact the administrator.") from exc
    except subprocess.TimeoutExpired as exc:
        raise EngineError(f"{name} exceeded its processing time limit.") from exc
    if result.returncode:
        raise EngineError(f"{name} could not process this document.")


def validate_docx(source: Path) -> None:
    try:
        with ZipFile(source) as package:
            entries = package.infolist()
            names = set(package.namelist())
            if len(entries) > MAX_ARCHIVE_ENTRIES or sum(entry.file_size for entry in entries) > MAX_ARCHIVE_BYTES:
                raise EngineError("The Word document expands beyond the allowed size.")
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
                raise EngineError("Upload a Microsoft Word DOCX document.")
            seen: set[str] = set()
            for entry in entries:
                name = entry.filename.casefold()
                path = PurePosixPath(name)
                if (
                    path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
                    or name in seen or entry.flag_bits & 1
                    or entry.external_attr >> 16 & 0o170000 == 0o120000
                ):
                    raise EngineError("The Word document contains an unsafe archive entry.")
                seen.add(name)
                if (
                    name.endswith((".bin", ".exe", ".dll", ".com", ".js", ".vbs"))
                    or name.startswith(("word/embeddings/", "word/activex/"))
                ):
                    raise EngineError("Word documents with macros or embedded objects are unsupported.")
                if name.endswith(".rels"):
                    if entry.file_size > 2 * 1024 * 1024:
                        raise EngineError("The Word document contains an oversized relationship list.")
                    for relation in ElementTree.fromstring(package.read(entry)):
                        if relation.get("TargetMode", "").lower() != "external":
                            continue
                        target = relation.get("Target", "").casefold()
                        if not (
                            relation.get("Type", "").endswith("/hyperlink")
                            and target.startswith(("https://", "http://", "mailto:"))
                        ):
                            raise EngineError("Word documents with external resources are unsupported.")
            if package.testzip() is not None:
                raise EngineError("The Word document archive is damaged.")
    except (BadZipFile, ElementTree.ParseError, OSError, NotImplementedError) as exc:
        raise EngineError("The Word document archive is invalid or damaged.") from exc


def _word_to_pdf(source: Path, output: Path, progress: Progress) -> dict:
    validate_docx(source)
    progress(25)
    with tempfile.TemporaryDirectory(prefix="word-render-", dir=output.parent) as working_dir:
        work = Path(working_dir)
        input_path = work / "document.docx"
        shutil.copyfile(source, input_path)
        _run_command(
            [
                "soffice",
                f"-env:UserInstallation={(work / 'profile').as_uri()}",
                "--headless", "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(work),
                str(input_path),
            ],
            "LibreOffice", work, 120,
        )
        rendered = work / "document.pdf"
        if not rendered.is_file():
            raise EngineError("LibreOffice did not produce a PDF from this Word document.")
        shutil.move(rendered, output)
    return {}


def _save(document: fitz.Document, output: Path, **kwargs) -> None:
    document.save(output, garbage=4, deflate=True, use_objstms=True, **kwargs)


def _merge(sources: list[Path], output: Path, progress: Progress, max_pages: int) -> dict:
    with fitz.open() as combined:
        for index, source in enumerate(sources):
            with open_pdf(source, max_pages=max_pages) as document:
                if len(combined) + len(document) > max_pages:
                    raise EngineError(f"The merged document would exceed the {max_pages}-page limit.")
                combined.insert_pdf(document, widgets=False)
            progress(15 + 70 * (index + 1) // len(sources))
        _save(combined, output)
    return {}


def _jpg_to_pdf(sources: list[Path], output: Path, progress: Progress, max_pages: int) -> dict:
    if len(sources) > max_pages:
        raise EngineError(f"The generated document would exceed the {max_pages}-page limit.")
    with fitz.open() as document:
        for index, source in enumerate(sources):
            try:
                with Image.open(source, formats=("JPEG",)) as image:
                    if image.width * image.height > MAX_IMAGE_PIXELS:
                        raise EngineError("A JPEG exceeds the 40 megapixel processing limit.")
                    orientation = image.getexif().get(274, 1)
                    if orientation not in (None, 1) or image.mode not in ("L", "RGB"):
                        with BytesIO() as corrected:
                            ImageOps.exif_transpose(image).convert("RGB").save(
                                corrected, format="JPEG", quality=92,
                            )
                            image_bytes = corrected.getvalue()
                    else:
                        image.load()
                        image_bytes = source.read_bytes()
                    with fitz.open(stream=image_bytes, filetype="jpeg") as picture:
                        with fitz.open(stream=picture.convert_to_pdf(), filetype="pdf") as page:
                            document.insert_pdf(page)
            except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
                raise EngineError("An uploaded JPEG is invalid or exceeds processing limits.") from exc
            progress(15 + 70 * (index + 1) // len(sources))
        _save(document, output)
    return {}


def _page_groups(document: fitz.Document, settings: dict) -> list[list[int]]:
    selection = settings.get("pages")
    if settings.get("split_mode") == "ranges" and selection and selection.strip().lower() != "all":
        ranges = [group.strip() for group in selection.split(",")]
        if any(not group or group.lower() == "all" for group in ranges):
            raise EngineError("Enter each split range explicitly, for example 1-3,4-6.")
        if len(ranges) > len(document):
            raise EngineError("Too many split ranges were supplied.")
        return [select_pages(group, len(document)) for group in ranges]
    return [[page] for page in select_pages(selection, len(document))]


def _split(document: fitz.Document, output: Path, settings: dict, progress: Progress) -> dict:
    groups = _page_groups(document, settings)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for index, pages in enumerate(groups):
            with fitz.open() as part:
                part.insert_pdf(document, from_page=pages[0], to_page=pages[-1], widgets=False)
                archive.writestr(f"part-{index + 1:03d}.pdf", part.tobytes(garbage=4, deflate=True))
            progress(15 + 75 * (index + 1) // len(groups))
    return {"parts": len(groups)}


def _pdf_to_jpg(document: fitz.Document, output: Path, settings: dict, progress: Progress) -> dict:
    pages = select_pages(settings.get("pages"), len(document))
    dpi = int(settings.get("dpi", 150))
    if not 72 <= dpi <= 300:
        raise EngineError("Select a JPG resolution between 72 and 300 DPI.")
    warnings = []
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        for index, number in enumerate(pages):
            page = document[number]
            area = page.rect.get_area()
            render_dpi = min(dpi, int(72 * (MAX_IMAGE_PIXELS / area) ** 0.5))
            if render_dpi < 1:
                raise EngineError("A page is too large to render as an image.")
            if render_dpi < dpi and not warnings:
                warnings.append("Resolution was reduced for oversized pages.")
            image = page.get_pixmap(dpi=render_dpi, colorspace=fitz.csRGB, alpha=False)
            archive.writestr(f"page-{number + 1:03d}.jpg", image.tobytes("jpeg", jpg_quality=90))
            progress(15 + 75 * (index + 1) // len(pages))
    return {"images": len(pages), "warnings": warnings}


def _ocr_pdf(
    document: fitz.Document, source: Path, output: Path, selected: list[int], settings: dict,
) -> dict:
    requested = settings.get("languages", ["eng"])
    check_ocr_languages(requested)
    command = [
        "ocrmypdf", "--force-ocr" if settings.get("ocr") == "force" else "--skip-text",
        "--rotate-pages", "--deskew", "--optimize", "0", "--output-type", "pdf",
        "--jobs", "1", "--tesseract-timeout", "90", "--language", "+".join(requested),
    ]
    if len(selected) != len(document):
        command.extend(("--pages", ",".join(str(page + 1) for page in selected)))
    _run_command([*command, str(source), str(output)], "OCRmyPDF", output.parent, 240)
    processed = len(selected) if settings.get("ocr") == "force" else sum(
        not document[index].get_text("text").strip() for index in selected
    )
    return {"ocr_pages": processed, "ocr_used": bool(processed), "ocr_languages": requested}


def _compress(document: fitz.Document, source: Path, output: Path, settings: dict) -> dict:
    level = settings.get("compression", "balanced")
    if level not in ("lossless", "balanced", "strong"):
        raise EngineError("Select a supported PDF compression level.")
    if level != "lossless":
        dpi, quality = (108, 60) if level == "strong" else (150, 80)
        document.rewrite_images(dpi_threshold=dpi * 6 // 5, dpi_target=dpi, quality=quality)
    _save(document, output)
    original_size = source.stat().st_size
    if output.stat().st_size > original_size:
        shutil.copyfile(source, output)
    return {"bytes_saved": original_size - output.stat().st_size}


def _modify_selected(document: fitz.Document, tool: str, settings: dict, progress: Progress) -> None:
    pages = select_pages(settings.get("pages"), len(document))
    if tool == "extract-pages":
        document.select(pages)
        return
    if tool == "delete-pages":
        removed = set(pages)
        remaining = [index for index in range(len(document)) if index not in removed]
        if not remaining:
            raise EngineError("Select fewer pages so the output contains at least one page.")
        document.select(remaining)
        return
    if tool == "rotate-pdf":
        rotation = int(settings.get("rotation", 90))
        if rotation not in (90, 180, 270):
            raise EngineError("Select a rotation of 90, 180, or 270 degrees.")
        for index in pages:
            page = document[index]
            page.set_rotation((page.rotation + rotation) % 360)
        return
    if tool == "watermark-pdf":
        text = str(settings.get("text", "")).strip()
        if not text or len(text) > 120 or any(ord(character) < 32 for character in text):
            raise EngineError("Enter watermark text between 1 and 120 characters on one line.")
        stamp = f"<strong>{escape(text)}</strong>"
    else:
        start = int(settings.get("start_number", 1))
        if not 1 <= start <= 999_999:
            raise EngineError("Choose a starting page number between 1 and 999999.")

    for ordinal, index in enumerate(pages):
        page = document[index]
        if page.rotation:
            page.remove_rotation()
        width, height = page.rect.width, page.rect.height
        if tool == "watermark-pdf":
            box = fitz.Rect(width * .07, height * .43, width * .93, height * .63)
            result, _ = page.insert_htmlbox(
                box, stamp, css="* { text-align: center; color: #345375; font-size: 30pt; }",
                opacity=.25,
            )
        else:
            box = fitz.Rect(width * .1, height * .92, width * .9, height * .99)
            result, _ = page.insert_htmlbox(
                box, str(start + ordinal), css="* { text-align: center; color: #26364b; font-size: 10pt; }",
            )
        if result < 0:
            raise EngineError("The text could not fit on one of the selected pages.")
        progress(15 + 70 * (ordinal + 1) // len(pages))


def _single_pdf(
    tool: str, source: Path, output: Path, settings: dict, progress: Progress, max_pages: int,
) -> dict:
    password = settings.get("password") if tool == "unlock-pdf" else None
    with open_pdf(source, max_pages=max_pages, password=password) as document:
        progress(15)
        if tool == "split-pdf":
            return _split(document, output, settings, progress)
        if tool == "pdf-to-jpg":
            return _pdf_to_jpg(document, output, settings, progress)
        if tool == "compress-pdf":
            return _compress(document, source, output, settings)
        if tool == "ocr-pdf":
            pages = select_pages(settings.get("pages"), len(document))
            return _ocr_pdf(document, source, output, pages, settings)
        if tool == "protect-pdf":
            password = str(settings.get("password") or "")
            if len(password) < 8 or len(password.encode("utf-8")) > 32:
                raise EngineError("Choose a password of at least 8 characters and at most 32 UTF-8 bytes.")
            _save(
                document, output, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=password,
                owner_pw=secrets.token_urlsafe(20),
            )
            return {}
        if tool == "unlock-pdf":
            if not document.metadata.get("encryption"):
                raise EngineError("This PDF has no password protection.")
            if not password or (not document.needs_pass and not document.authenticate(password)):
                raise EngineError("The PDF password is incorrect.")
            # qpdf rewrites encrypted content streams after PyMuPDF has inspected
            # the input. The password stays out of command-line arguments.
            with tempfile.TemporaryDirectory(prefix="unlock-", dir=output.parent) as directory:
                work = Path(directory)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=work, delete=False) as request:
                    json.dump({
                        "inputFile": str(source), "outputFile": str(output),
                        "password": password, "decrypt": "",
                    }, request)
                _run_command(["qpdf", f"--job-json-file={request.name}"], "qpdf", work, 90)
            return {}
        _modify_selected(document, tool, settings, progress)
        _save(document, output, encryption=fitz.PDF_ENCRYPT_NONE)
    return {}


def run_tool(
    tool: str, sources: list[Path], output: Path, settings: dict, progress: Progress,
    *, max_pages: int = 500,
) -> dict:
    """Apply a PDF utility and verify the persisted output before returning."""
    if tool not in TOOL_OUTPUTS or tool == "pdf-to-word":
        raise EngineError("This tool is unavailable.")
    if not sources or (tool not in ("merge-pdf", "jpg-to-pdf") and len(sources) != 1):
        raise EngineError("Provide the correct number of input files for this tool.")
    if tool == "merge-pdf" and len(sources) < 2:
        raise EngineError("Select at least two PDFs to merge.")
    output = output.resolve()
    sources = [path.resolve() for path in sources]
    progress(8)
    if tool == "merge-pdf":
        metrics = _merge(sources, output, progress, max_pages)
    elif tool == "jpg-to-pdf":
        metrics = _jpg_to_pdf(sources, output, progress, max_pages)
    elif tool == "word-to-pdf":
        metrics = _word_to_pdf(sources[0], output, progress)
    else:
        metrics = _single_pdf(tool, sources[0], output, settings, progress, max_pages)

    if TOOL_OUTPUTS[tool] == ".zip":
        with ZipFile(output) as archive:
            if not archive.namelist() or archive.testzip() is not None:
                raise EngineError("The output archive could not be validated.")
    else:
        with fitz.open(output, filetype="pdf") as result:
            if tool == "protect-pdf" and not result.authenticate(settings["password"]):
                raise EngineError("The protected PDF could not be validated.")
            if not result.is_pdf or not 1 <= len(result) <= max_pages:
                raise EngineError("The output PDF could not be validated within the page limit.")
            metrics["pages"] = len(result)
    metrics.setdefault("warnings", [])
    progress(95)
    return metrics
