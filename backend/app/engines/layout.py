"""Recover editable content and infer reading order from PDF page geometry."""

from collections import Counter
from io import BytesIO
from math import atan2, degrees
import re
from statistics import median
from urllib.parse import urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError
import pymupdf

from .layout_types import Columns, Element, Line, PageLayout, Paragraph, Picture, Rect, Span, Table
from .pdf_source import PageFacts

BULLET = re.compile(r"^\s*[•◦▪‣∙●■]\s*")
NUMBERED = re.compile(r"^\s*(?:\d{1,3}|[a-zA-Z])[.)]\s+")
PAGE_FIELD = re.compile(r"^(?:page\s+)?(\d+)(?:\s*(?:of|/)\s*\d+)?$", re.IGNORECASE)
IMAGE_BYTES_PER_PAGE = 40 * 1024 * 1024
MAX_IMAGE_PIXELS = 18_000_000


def enclosing(items: list) -> Rect:
    result = Rect(items[0].box)
    for item in items[1:]:
        result |= item.box
    return result


def overlap(first: Rect, second: Rect) -> float:
    return (first & second).get_area() / max(first.get_area(), 0.01)


def acceptable_link(link: dict) -> str | int | None:
    if link["kind"] == pymupdf.LINK_GOTO and link.get("page", -1) >= 0:
        return link["page"] + 1
    if link["kind"] != pymupdf.LINK_URI:
        return None
    value = link.get("uri") or ""
    if len(value) > 2048 or any(ord(char) < 32 for char in value):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme in {"https", "http"} and parsed.netloc:
        return value
    if parsed.scheme == "mailto" and parsed.path:
        return value
    return None


def _span_runs(record: dict, transform: pymupdf.Matrix, links: list) -> list[Span]:
    runs: list[Span] = []
    for char in record["chars"]:
        box = Rect(char["bbox"]) * transform
        link = next((target for area, target in links if overlap(box, area) >= 0.52), None)
        if runs and runs[-1].link == link:
            runs[-1].text += char["c"]
            runs[-1].box |= box
        else:
            runs.append(
                Span(char["c"], box, record["size"], record["font"], record["flags"], record["color"], link)
            )
    return runs


def _paragraphs(lines: list[Line]) -> list[Paragraph]:
    groups: list[list[Line]] = []
    for line in lines:
        if not groups:
            groups.append([line])
            continue
        previous = groups[-1][-1]
        line_height = max(1, previous.box.height)
        gap = line.box.y0 - previous.box.y1
        heading_shift = abs(line.spans[0].size - previous.spans[0].size) > 2.5
        left_shift = abs(line.box.x0 - previous.box.x0)
        starts_list = BULLET.match(line.text) or NUMBERED.match(line.text)
        if gap < -line_height * 0.65 or gap > line_height * 0.7 or left_shift > 38 or heading_shift or starts_list:
            groups.append([line])
        else:
            groups[-1].append(line)
    return [Paragraph(enclosing(group), group) for group in groups]


def _infer_role(paragraph: Paragraph, body_size: float) -> None:
    first = paragraph.lines[0]
    if BULLET.match(first.text):
        paragraph.role = "bullet"
        return
    if NUMBERED.match(first.text):
        paragraph.role = "number"
        return
    size = median([span.size for span in first.spans])
    bold = any(span.flags & pymupdf.TEXT_FONT_BOLD for span in first.spans)
    if len(paragraph.text) < 160 and (size > body_size * 1.23 or (bold and size > body_size * 1.13)):
        paragraph.role = "heading1" if size >= body_size * 1.6 else "heading2"


def _table_extract(candidate) -> Table | None:
    rows = [[(cell or "").strip() for cell in row] for row in candidate.extract()]
    if len(rows) < 2 or len(rows[0]) < 2 or len(rows) * len(rows[0]) > 2000:
        return None
    if sum(bool(cell) for row in rows for cell in row) < 3:
        return None
    box = Rect(candidate.bbox)
    if box.is_empty:
        return None
    column_count = len(rows[0])
    grid = [row.cells for row in candidate.rows]
    horizontal = next((cells for cells in grid if all(cells)), [])
    if horizontal:
        edges = [horizontal[0][0]] + [cell[2] for cell in horizontal]
    else:
        edges = [box.x0 + box.width * index / column_count for index in range(column_count + 1)]
    widths = [max(1, right - left) for left, right in zip(edges, edges[1:])]
    merges: list[tuple[int, int, int, int]] = []
    row_tops = [row.bbox[1] for row in candidate.rows]
    for row_index, cells in enumerate(grid):
        for column_index, cell in enumerate(cells):
            if not cell:
                continue
            right = max(
                (position for position in range(column_index, column_count) if edges[position] < cell[2] - 2),
                default=column_index,
            )
            bottom = max(
                (position for position in range(row_index, len(rows)) if row_tops[position] < cell[3] - 2),
                default=row_index,
            )
            if (bottom != row_index or right != column_index) and all(
                not grid[y][x]
                for y in range(row_index, bottom + 1)
                for x in range(column_index, right + 1)
                if (y, x) != (row_index, column_index)
            ):
                merges.append((row_index, column_index, bottom, right))
    return Table(box, rows, widths, merges)


def _tables(page: pymupdf.Page, transform: pymupdf.Matrix) -> list[Table]:
    if page.rotation in {90, 270}:
        # PyMuPDF table coordinates follow unrotated grid axes. A quarter-turn
        # is handled by paragraph reconstruction instead of a sideways grid.
        return []
    tables = []
    drawn = page.get_drawings()
    for candidate in page.find_tables(strategy="lines", paths=drawn).tables:
        found = _table_extract(candidate)
        if found is not None:
            found.box *= transform
            tables.append(found)
    for candidate in page.find_tables(strategy="text", min_words_vertical=3, min_words_horizontal=1).tables:
        found = _table_extract(candidate)
        if found is None or len(found.rows) < 3:
            continue
        cells = [cell for row in found.rows for cell in row if cell]
        numerical = sum(bool(re.search(r"\d", cell)) for cell in cells)
        short_cells = sum(len(cell.split()) <= 5 for cell in cells)
        # Text-only grids are ambiguous. Require repeated short entries and a
        # meaningful numeric column to avoid turning body columns into tables.
        if short_cells / len(cells) < 0.8 or numerical < len(found.rows) - 1:
            continue
        found.box *= transform
        if all(overlap(found.box, table.box) < 0.25 for table in tables):
            tables.append(found)
    return tables


def _picture(record: dict, box: Rect, page_transform: pymupdf.Matrix) -> Picture | None:
    orientation = pymupdf.Matrix(*record["transform"]) * page_transform
    angle = degrees(atan2(orientation.b, orientation.a))
    flip = orientation.a * orientation.d - orientation.b * orientation.c < 0
    with Image.open(BytesIO(record["image"])) as image:
        if image.width * image.height > MAX_IMAGE_PIXELS:
            return None
        mask = record.get("mask")
        if mask:
            with Image.open(BytesIO(mask)) as alpha:
                if alpha.size == image.size:
                    image = image.convert("RGBA")
                    image.putalpha(alpha.convert("L"))
        elif record["ext"] in {"png", "jpeg", "jpg", "gif", "bmp", "tiff"} and abs(angle) < 0.2 and not flip:
            return Picture(box, record["image"])
        else:
            image = image.convert("RGBA")
        if flip:
            image = ImageOps.flip(image)
        if abs(angle) >= 0.2:
            image = image.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True)
        encoded = BytesIO()
        image.save(encoded, format="PNG")
        return Picture(box, encoded.getvalue())


def _illustrations(page: pymupdf.Page, contents: list[Element]) -> list[Picture]:
    transform = page.rotation_matrix
    paths = page.get_drawings()
    if not paths or len(paths) > 600:
        return []
    parts = page.cluster_drawings(drawings=paths)
    figures = []
    for original in parts[:24]:
        box = original * transform
        if box.width < 28 or box.height < 18 or box.get_area() > page.rect.get_area() * 0.75:
            continue
        if any(overlap(box, item.box) > 0.08 or overlap(item.box, box) > 0.3 for item in contents):
            continue
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), clip=box, alpha=False, annots=False)
        if pixmap.width and pixmap.height:
            figures.append(Picture(box, pixmap.tobytes("png"), "Vector illustration from the source PDF"))
    return figures


def extract_layout(page: pymupdf.Page, facts: PageFacts, settings: dict, *, ocr: bool) -> PageLayout:
    layout = PageLayout(page.number + 1, page.rect.width, page.rect.height, facts.kind, source_rotation=page.rotation)
    transform = page.rotation_matrix
    links = []
    if settings.get("preserve_hyperlinks", True):
        for link in page.get_links():
            target = acceptable_link(link)
            if target is not None:
                links.append((Rect(link["from"]), target))
    tables = []
    if facts.reliable_text and settings.get("preserve_tables", True):
        try:
            tables = _tables(page, transform)
        except (RuntimeError, ValueError, IndexError, TypeError):
            layout.warnings.append(f"Page {layout.number}: table detection encountered an unsupported grid.")
    layout.contents.extend(tables)

    paragraphs: list[Paragraph] = []
    images: list[Picture] = []
    image_bytes = 0
    flags = pymupdf.TEXTFLAGS_RAWDICT
    preserve_images = settings.get("preserve_images", True)
    if not preserve_images:
        flags &= ~pymupdf.TEXT_PRESERVE_IMAGES
    for block in page.get_text("rawdict", flags=flags)["blocks"]:
        if block["type"] == 1:
            box = Rect(block["bbox"]) * transform
            if box.is_empty:
                continue
            if ocr and facts.needs_ocr and overlap(box, page.rect) > 0.8 and box.get_area() > page.rect.get_area() * 0.35:
                # A source scan would duplicate its reconstructed, editable contents.
                continue
            image_bytes += len(block["image"])
            if image_bytes > IMAGE_BYTES_PER_PAGE:
                layout.warnings.append(f"Page {layout.number}: some images exceeded the per-page image budget.")
                continue
            try:
                picture = _picture(block, box, transform)
            except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
                picture = None
            if picture is None:
                layout.warnings.append(f"Page {layout.number}: an embedded image could not be carried into Word.")
            else:
                images.append(picture)
            continue
        if block["type"] != 0:
            continue
        lines = []
        for record in block["lines"]:
            box = Rect(record["bbox"]) * transform
            if any(overlap(box, table.box) > 0.65 for table in tables):
                continue
            spans = [span for entry in record["spans"] for span in _span_runs(entry, transform, links) if span.text]
            if spans and any(span.text.strip() for span in spans):
                lines.append(Line(box, spans))
        paragraphs.extend(_paragraphs(lines))
    if paragraphs:
        sizes = Counter()
        for paragraph in paragraphs:
            for line in paragraph.lines:
                for span in line.spans:
                    if span.text.strip():
                        sizes[round(span.size, 1)] += len(span.text.strip())
        layout.body_size = sizes.most_common(1)[0][0] if sizes else 11
        for item in paragraphs:
            _infer_role(item, layout.body_size)
        left_edges = [paragraph.box.x0 for paragraph in paragraphs if paragraph.role in {"bullet", "number"}]
        if left_edges:
            origin = min(left_edges)
            for paragraph in paragraphs:
                if paragraph.role in {"bullet", "number"}:
                    paragraph.list_level = min(3, max(0, round((paragraph.box.x0 - origin) / 23)))
    layout.contents.extend(paragraphs)
    layout.contents.extend(images)
    if preserve_images and not facts.needs_ocr:
        try:
            layout.contents.extend(_illustrations(page, layout.contents))
        except (RuntimeError, ValueError):
            layout.warnings.append(f"Page {layout.number}: a vector illustration could not be reproduced.")
    return layout


def _signature(text: str) -> str:
    return " ".join(text.lower().split())


def running_text(document: pymupdf.Document, pages: list[int]) -> tuple[set[str], set[str]]:
    locations = [Counter(), Counter()]
    for index in pages:
        page = document[index]
        if page.rotation:
            continue
        width, height = page.rect.width, page.rect.height
        for section, clip in enumerate([Rect(0, 0, width, height * 0.115), Rect(0, height * 0.885, width, height)]):
            blocks = page.get_text("blocks", clip=clip, flags=pymupdf.TEXTFLAGS_TEXT)
            locations[section].update(
                {_signature(block[4]) for block in blocks if block[4].strip() and len(block[4].strip()) < 140}
            )
    threshold = max(2, (len(pages) + 2) // 3)
    return tuple({text for text, count in location.items() if count >= threshold} for location in locations)


def assign_running_text(layout: PageLayout, headers: set[str], footers: set[str]) -> None:
    body = []
    for item in layout.contents:
        if isinstance(item, Paragraph):
            text = _signature(item.text)
            if item.box.y1 <= layout.height * 0.115 and text in headers:
                layout.headers.append(item)
                continue
            if item.box.y0 >= layout.height * 0.885:
                field = PAGE_FIELD.fullmatch(text)
                if field and int(field[1]) == layout.number:
                    item.role = "page-number"
                if text in footers or item.role == "page-number":
                    layout.footers.append(item)
                    continue
        body.append(item)
    layout.contents = body


def _gutter(items: list[Element], left: float, right: float) -> float | None:
    if len(items) < 2 or right - left < 150:
        return None
    best: tuple[float, float] | None = None
    for step in range(5, 16):
        cut = left + (right - left) * step / 20
        before = [item for item in items if item.box.x1 < cut - 3]
        after = [item for item in items if item.box.x0 > cut + 3]
        crossing = len(items) - len(before) - len(after)
        if not before or not after or crossing > (len(before) + len(after)) * 0.67:
            continue
        before_box, after_box = enclosing(before), enclosing(after)
        shared_height = min(before_box.y1, after_box.y1) - max(before_box.y0, after_box.y0)
        if shared_height < min(13, before_box.height * 0.7, after_box.height * 0.7):
            continue
        if min(before_box.width, after_box.width) < 35:
            continue
        open_space = after_box.x0 - before_box.x1
        score = min(len(before), len(after)) * 4 + shared_height * 0.08 + min(open_space, 72) * 0.07 - crossing
        candidate = (score, (before_box.x1 + after_box.x0) / 2)
        if best is None or candidate > best:
            best = candidate
    return best[1] if best else None


def _sorted(items: list[Element]) -> list[Element]:
    return sorted(items, key=lambda item: (round(item.box.y0 / 3), item.box.x0))


def order_elements(layout: PageLayout) -> list[Element | Columns]:
    """Read spanning elements first, then each column in a shared vertical band."""
    items = _sorted(layout.contents)
    cut = _gutter(items, 0, layout.width)
    if cut is None:
        return items
    spanning = [item for item in items if item.box.x0 <= cut <= item.box.x1]
    remaining = [item for item in items if not (item.box.x0 <= cut <= item.box.x1)]
    ordered: list[Element | Columns] = []
    for span in [*spanning, None]:
        section = [item for item in remaining if span is None or item.box.y0 < span.box.y0 - 2]
        remaining = [item for item in remaining if span is not None and item.box.y0 >= span.box.y0 - 2]
        groups = [
            [item for item in section if item.box.x1 < cut],
            [item for item in section if item.box.x0 > cut],
        ]
        if all(groups):
            extra_groups = []
            for group, (left, right) in zip(groups, [(0, cut), (cut, layout.width)]):
                extra = _gutter(group, left, right)
                if extra is None:
                    extra_groups.append(group)
                else:
                    extra_groups.extend(
                        [[item for item in group if item.box.x0 < extra], [item for item in group if item.box.x0 >= extra]]
                    )
            ordered.append(Columns(enclosing(section), extra_groups))
        else:
            ordered.extend(section)
        if span is not None:
            ordered.append(span)
    return ordered
