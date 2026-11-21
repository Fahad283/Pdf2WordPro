"""Page-specific OCR using bounded rasterization and Tesseract word geometry."""

from bisect import bisect_right
from collections import defaultdict
import csv
from dataclasses import dataclass
from io import StringIO
from math import atan2, degrees, sqrt
from pathlib import Path
import re
import shutil
from statistics import median
import subprocess
from tempfile import TemporaryDirectory

import cv2
import numpy as np
from PIL import Image, ImageOps
import pymupdf

from .layout import enclosing
from .layout_types import Line, Paragraph, Rect, Span, Table
from .pdf_source import EngineError
from .process_env import processor_environment

LANGUAGE_CODE = re.compile(r"[A-Za-z0-9_]{2,32}\Z")
MAX_PIXELS = 18_000_000
MAX_SIDE = 5600


@dataclass
class OCRPage:
    paragraphs: list[Paragraph]
    tables: list[Table]
    width: float
    height: float
    confidence: float | None
    rotation: int
    used_sparse_segmentation: bool


def raster_page(
    page: pymupdf.Page, dpi: int, *, grayscale: bool = False
) -> pymupdf.Pixmap:
    width, height = page.rect.width, page.rect.height
    scale = min(dpi / 72, sqrt(MAX_PIXELS / (width * height)), MAX_SIDE / max(width, height))
    colorspace = pymupdf.csGRAY if grayscale else pymupdf.csRGB
    return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=colorspace, alpha=False)


def tesseract_languages() -> set[str]:
    executable = shutil.which("tesseract")
    if not executable:
        raise EngineError("OCR is unavailable because Tesseract is not installed on the worker.")
    try:
        result = subprocess.run(
            [executable, "--list-langs"],
            capture_output=True,
            check=True,
            timeout=12,
            text=True,
            env=processor_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EngineError("Tesseract could not load its language configuration.") from exc
    return {line for line in result.stdout.splitlines() if LANGUAGE_CODE.fullmatch(line)}


def check_ocr_languages(languages: list[str]) -> set[str]:
    if not languages or len(languages) > 12 or any(
        not isinstance(code, str) or not LANGUAGE_CODE.fullmatch(code) or code in {"osd", "equ"}
        for code in languages
    ):
        raise EngineError("Choose at least one valid OCR language.")
    available = tesseract_languages()
    missing = sorted(set(languages) - available)
    if missing:
        raise EngineError(
            f"OCR language data is missing for {', '.join(missing)}. "
            "Install those Tesseract language packs on the worker or select installed languages."
        )
    return available


def _orientation(path: Path) -> int:
    try:
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "osd", "--psm", "0"],
            capture_output=True,
            timeout=22,
            text=True,
            env=processor_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    angle = re.search(r"^Rotate:\s*(90|180|270)\s*$", result.stdout, flags=re.MULTILINE)
    confidence = re.search(r"^Orientation confidence:\s*([0-9.]+)", result.stdout, flags=re.MULTILINE)
    if angle and confidence and float(confidence[1]) >= 5:
        return int(angle[1])
    return 0


def _deskew(image: Image.Image) -> Image.Image:
    sample = image.copy()
    sample.thumbnail((1050, 1050))
    array = np.asarray(sample)
    if min(array.shape) < 40:
        return image
    _, foreground = cv2.threshold(array, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    edges = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, np.ones((1, 15), np.uint8))
    found = cv2.HoughLinesP(
        edges, 1, np.pi / 360, threshold=45, minLineLength=max(35, array.shape[1] // 12), maxLineGap=12
    )
    if found is None:
        return image
    angles = []
    for x0, y0, x1, y1 in found.reshape(-1, 4):
        if x0 > x1:
            x0, x1, y0, y1 = x1, x0, y1, y0
        angle = degrees(atan2(y1 - y0, x1 - x0))
        if abs(angle) <= 9:
            angles.append(angle)
    if len(angles) < 3:
        return image
    correction = median(angles)
    if abs(correction) < 0.45:
        return image
    return image.rotate(correction, resample=Image.Resampling.BICUBIC, fillcolor=255)


def _preprocess(pixmap: pymupdf.Pixmap, image_path: Path, detect_rotation: bool) -> tuple[Image.Image, int]:
    cv2.setNumThreads(1)
    image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
    image = ImageOps.autocontrast(image, cutoff=0.3)
    height, width = image.height, image.width
    if min(height, width) > 5:
        clean = cv2.medianBlur(np.asarray(image), 3)
        image = Image.fromarray(clean)
    rotation = 0
    if detect_rotation:
        image.save(image_path, dpi=(250, 250))
        rotation = _orientation(image_path)
    if rotation:
        image = image.rotate(-rotation, expand=True, fillcolor=255)
    return _deskew(image), rotation


def _recognize(path: Path, languages: list[str], *, segmentation: str) -> str:
    try:
        result = subprocess.run(
            [
                "tesseract", str(path), "stdout", "-l", "+".join(languages), "--psm", segmentation,
                "-c", "tessedit_create_tsv=1",
            ],
            capture_output=True,
            timeout=125,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=processor_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        raise EngineError("OCR exceeded the time limit on a page. Try a smaller page selection.") from exc
    except subprocess.CalledProcessError as exc:
        error = (exc.stderr or "").lower()
        if "failed loading language" in error or "couldn't load any languages" in error:
            raise EngineError(
                f"Tesseract could not load OCR language data for {', '.join(languages)}. "
                "Reinstall those language packs or select installed languages."
            ) from exc
        raise EngineError("Tesseract could not recognize this page with the selected OCR languages.") from exc
    except OSError as exc:
        raise EngineError("Tesseract could not recognize this page with the selected OCR languages.") from exc
    return result.stdout


def _decode(tsv: str, x_scale: float, y_scale: float) -> tuple[list[Paragraph], float | None]:
    groups: dict[tuple[str, str], dict[str, list[Span]]] = defaultdict(lambda: defaultdict(list))
    weighted_confidence = total_characters = 0.0
    for row in csv.DictReader(StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (row.get("text") or "").strip()
        if row.get("level") != "5" or not text:
            continue
        try:
            confidence = float(row["conf"])
            left = float(row["left"]) * x_scale
            top = float(row["top"]) * y_scale
            width = float(row["width"]) * x_scale
            height = float(row["height"]) * y_scale
        except (ValueError, KeyError, TypeError):
            continue
        if confidence < 0 or width <= 0 or height <= 0:
            continue
        weighted_confidence += confidence * len(text)
        total_characters += len(text)
        line = groups[(row["block_num"], row["par_num"])][row["line_num"]]
        box = Rect(left, top, left + width, top + height)
        line.append(Span((" " if line else "") + text, box, max(6, min(65, height * 1.12))))
    paragraphs = []
    for group in groups.values():
        lines = [Line(enclosing(spans), spans) for spans in group.values()]
        paragraphs.append(Paragraph(enclosing(lines), lines))
    average = weighted_confidence / total_characters if total_characters else None
    return paragraphs, round(average, 1) if average is not None else None


def _ruling_positions(lengths: np.ndarray, threshold: float) -> list[float]:
    indices = np.flatnonzero(lengths >= threshold)
    if not len(indices):
        return []
    runs = np.split(indices, np.flatnonzero(np.diff(indices) > 2) + 1)
    return [float(run.mean()) for run in runs]


def _grid_rulings(image: Image.Image, width: float, height: float) -> list[tuple[list[float], list[float]]]:
    sample = image.copy()
    sample.thumbnail((1500, 1500))
    _, binary = cv2.threshold(np.asarray(sample), 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((1, max(18, sample.width // 30)), np.uint8))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((max(18, sample.height // 55), 1), np.uint8))
    connected = cv2.dilate(cv2.bitwise_or(horizontal, vertical), np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = sorted((cv2.boundingRect(contour) for contour in contours), key=lambda box: box[2] * box[3], reverse=True)
    grids = []
    for left, top, box_width, box_height in candidates[:12]:
        if box_width < sample.width * 0.14 or box_height < sample.height * 0.055:
            continue
        x_end, y_end = left + box_width, top + box_height
        x_positions = _ruling_positions(np.count_nonzero(vertical[top:y_end, left:x_end], axis=0), box_height * 0.42)
        y_positions = _ruling_positions(np.count_nonzero(horizontal[top:y_end, left:x_end], axis=1), box_width * 0.48)
        if not (3 <= len(x_positions) <= 28 and 3 <= len(y_positions) <= 46):
            continue
        x = [(left + position) * width / sample.width for position in x_positions]
        y = [(top + position) * height / sample.height for position in y_positions]
        if min(right - left for left, right in zip(x, x[1:])) < 8 or min(bottom - top for top, bottom in zip(y, y[1:])) < 6:
            continue
        grids.append((x, y))
    return grids


def _ocr_tables(
    paragraphs: list[Paragraph], grids: list[tuple[list[float], list[float]]]
) -> list[Table]:
    words = [span for paragraph in paragraphs for line in paragraph.lines for span in line.spans]
    tables = []
    for x, y in grids:
        cells: list[list[list[str]]] = [[[] for _ in x[1:]] for _ in y[1:]]
        for word in words:
            center_x = (word.box.x0 + word.box.x1) / 2
            center_y = (word.box.y0 + word.box.y1) / 2
            column, row = bisect_right(x, center_x) - 1, bisect_right(y, center_y) - 1
            if 0 <= row < len(y) - 1 and 0 <= column < len(x) - 1:
                cells[row][column].append(word.text.strip())
        occupied = sum(bool(cell) for row in cells for cell in row)
        if occupied >= max(3, len(cells) * len(cells[0]) * 0.3):
            values = [[" ".join(cell) for cell in row] for row in cells]
            widths = [right - left for left, right in zip(x, x[1:])]
            tables.append(Table(Rect(x[0], y[0], x[-1], y[-1]), values, widths))
    return tables


def ocr_page(
    page: pymupdf.Page,
    languages: list[str],
    *,
    detect_rotation: bool,
    preserve_tables: bool = False,
    work_dir: Path | None = None,
) -> OCRPage:
    with TemporaryDirectory(prefix="page-ocr-", dir=work_dir) as directory:
        path = Path(directory) / "page.png"
        pixmap = raster_page(page, 260, grayscale=True)
        image, rotation = _preprocess(pixmap, path, detect_rotation)
        width, height = page.rect.width, page.rect.height
        if rotation in {90, 270}:
            width, height = height, width
        dpi = round(72 * min(image.width / width, image.height / height))
        image.save(path, dpi=(max(70, dpi), max(70, dpi)))
        x_scale, y_scale = width / image.width, height / image.height
        tsv = _recognize(path, languages, segmentation="3")
        paragraphs, confidence = _decode(tsv, x_scale, y_scale)
        used_sparse_segmentation = False
        if not paragraphs:
            # Automatic segmentation can miss disconnected text, including
            # some right-to-left layouts. Sparse detection keeps word boxes.
            tsv = _recognize(path, languages, segmentation="11")
            paragraphs, confidence = _decode(tsv, x_scale, y_scale)
            used_sparse_segmentation = bool(paragraphs)
        tables = _ocr_tables(paragraphs, _grid_rulings(image, width, height)) if preserve_tables else []
        return OCRPage(paragraphs, tables, width, height, confidence, rotation, used_sparse_segmentation)
