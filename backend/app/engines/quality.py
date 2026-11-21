"""Check newly generated Word packages and compare LibreOffice renders."""

from collections import Counter
from io import BytesIO
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.opc.exceptions import PackageNotFoundError
from lxml import etree
import numpy as np
from PIL import Image, ImageOps
import pymupdf

from .pdf_source import EngineError
from .process_env import processor_environment

DOCX_MEMBERS = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
WORD_NAMESPACES = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def verify_docx(path: Path, expected_images: int) -> dict:
    """Reopen the output and verify the XML, image reference IDs, and ZIP package."""
    try:
        with ZipFile(path) as package:
            names = set(package.namelist())
            if not DOCX_MEMBERS <= names or package.testzip():
                raise EngineError("The generated Word package did not pass its integrity check.")
            for member in names:
                if member.endswith((".xml", ".rels")):
                    with package.open(member) as data:
                        etree.parse(data, parser=etree.XMLParser(resolve_entities=False, no_network=True))
        document = Document(path)
        references = etree.XPath("//a:blip/@r:embed", namespaces=WORD_NAMESPACES)(document._element)
        for identifier in set(references):
            rel = document.part.rels.get(identifier)
            if rel is None or rel.is_external or rel.reltype != RELATIONSHIP_TYPE.IMAGE or not rel.target_part.blob:
                raise EngineError("The generated Word package has a missing image.")
    except (OSError, BadZipFile, etree.XMLSyntaxError, KeyError, ValueError, PackageNotFoundError) as exc:
        if isinstance(exc, EngineError):
            raise
        raise EngineError("The generated Word file could not be reopened or validated.") from exc
    if len(references) != expected_images:
        raise EngineError("The generated Word document did not preserve its expected images.")
    return {
        "docx_valid": True,
        "embedded_images": len(references),
        "native_paragraphs": len(document._element.xpath(".//w:p")),
        "native_tables": len(document._element.xpath(".//w:tbl")),
        "docx_size_bytes": path.stat().st_size,
    }


def _thumbnail(page: pymupdf.Page) -> np.ndarray:
    width, height = page.rect.width, page.rect.height
    zoom = 150 / max(width, height)
    image = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
    with Image.open(BytesIO(image.tobytes("png"))) as picture:
        return np.asarray(
            ImageOps.pad(picture.convert("L"), (150, 150), method=Image.Resampling.LANCZOS, color=255), dtype=float
        )


def _score(source: pymupdf.Page, result: pymupdf.Page) -> float:
    expected, produced = _thumbnail(source), _thumbnail(result)
    content = (expected < 238) | (produced < 238)
    if not content.any():
        return 1.0
    return 1 - float(np.abs(expected - produced)[content].mean() / 255)


def _words(document: pymupdf.Document, indexes: list[int]) -> Counter:
    tokens = Counter()
    for index in indexes:
        tokens.update(TOKEN.findall(document[index].get_text("text").casefold()[:300_000]))
    return tokens


def _compare(source: pymupdf.Document, output: pymupdf.Document, selected: list[int], mode: str) -> tuple[dict, list[str]]:
    warnings = []
    metrics: dict = {"render_validated": True, "rendered_pages": len(output)}
    if len(selected) != len(output):
        warnings.append(f"Word rendered {len(output)} pages from {len(selected)} selected PDF pages. Pagination changed.")
    else:
        sample = sorted({round(index * (len(selected) - 1) / 7) for index in range(8)})
        scores = [_score(source[selected[index]], output[index]) for index in sample]
        similarity = round(sum(scores) / len(scores), 3)
        metrics["visual_similarity"] = similarity
        metrics["compared_pages"] = len(scores)
        if similarity < 0.84:
            warnings.append("The rendered Word pages differ in the placement or appearance of some source content.")
    if mode != "visual":
        original = _words(source, selected)
        recovered = _words(output, list(range(len(output))))
        if original:
            recall = round(sum((original & recovered).values()) / sum(original.values()), 3)
            metrics["source_word_recall"] = recall
            if recall < 0.9:
                warnings.append("The rendered Word file contains fewer matching source words than expected.")
    empty_pages = 0
    for page in output:
        if not page.get_text("text").strip() and _thumbnail(page).min() > 242:
            empty_pages += 1
    if empty_pages:
        metrics["empty_rendered_pages"] = empty_pages
        warnings.append(f"LibreOffice detected {empty_pages} visually empty page(s) in the Word output.")
    return metrics, warnings


def validate_render(
    path: Path, source: pymupdf.Document, selected: list[int], mode: str
) -> tuple[dict, list[str]]:
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if not executable:
        return {"render_validated": False}, ["Layout comparison requires LibreOffice on the worker."]
    with TemporaryDirectory(prefix="word-render-", dir=path.parent) as directory:
        workspace = Path(directory)
        profile = (workspace / "profile").as_uri()
        try:
            subprocess.run(
                [
                    executable,
                    f"-env:UserInstallation={profile}",
                    "--headless",
                    "--convert-to",
                    "pdf:writer_pdf_Export",
                    "--outdir",
                    str(workspace),
                    str(path.resolve()),
                ],
                capture_output=True,
                check=True,
                timeout=110,
                env=processor_environment(workspace),
            )
            rendered_path = workspace / f"{path.stem}.pdf"
            with pymupdf.open(rendered_path) as rendered:
                if not len(rendered):
                    raise ValueError("No rendered pages")
                return _compare(source, rendered, selected, mode)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            return {"render_validated": False}, [
                "LibreOffice could not finish the layout comparison. The Word package passed its integrity check."
            ]
