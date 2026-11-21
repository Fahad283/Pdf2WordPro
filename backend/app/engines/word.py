"""Write editable Word paragraphs, drawing objects, tables, and running text."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import unicodedata

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.image.exceptions import UnrecognizedImageError
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.shared import Pt, RGBColor
from docx.text.run import Run
import pymupdf

from .layout import BULLET, NUMBERED, enclosing, order_elements
from .layout_types import Columns, Element, PageLayout, Paragraph, Picture, Span, Table
from .pdf_source import EngineError

SUBSET = re.compile(r"^[A-Z]{6}\+")
LIST_PREFIX = re.compile(r"([0-9]+|[a-zA-Z])")
PAGE_VALUE = re.compile(r"^(.*?)(\d+)(.*)$")
MAX_WORD_POINTS = 1584
MAX_WORD_MEDIA_BYTES = 120 * 1024 * 1024
FONT_ALIASES = {"Helvetica": "Arial", "Times": "Times New Roman", "Courier": "Courier New"}


def _element(tag: str, **attributes: str | int):
    element = OxmlElement(tag)
    for key, value in attributes.items():
        element.set(qn(f"w:{key}"), str(value))
    return element


def _replace(parent, name: str, **attributes: str | int) -> None:
    previous = parent.find(qn(name))
    child = _element(name, **attributes)
    if previous is None:
        parent.append(child)
    else:
        parent.replace(previous, child)


def _xml_text(value: str) -> str:
    return "".join(
        char
        for char in value
        if char in "\t\n\r" or 0x20 <= ord(char) <= 0xD7FF or 0xE000 <= ord(char) <= 0xFFFD
        or 0x10000 <= ord(char) <= 0x10FFFF
    )


def _rtl(text: str) -> bool:
    directions = [unicodedata.bidirectional(char) for char in text]
    strong = [value for value in directions if value in {"R", "AL", "L"}]
    return bool(strong and sum(value in {"R", "AL"} for value in strong) > len(strong) / 2)


def _bookmark(paragraph, page: int) -> None:
    start = _element("w:bookmarkStart", id=page, name=f"SourcePage{page}")
    end = _element("w:bookmarkEnd", id=page)
    paragraph._p.insert(1 if paragraph._p.pPr is not None else 0, start)
    paragraph._p.append(end)


def _font_name(source: str, rtl: bool) -> str:
    name = SUBSET.sub("", source)
    name = re.sub(r"[-,](?:BoldItalic|BoldOblique|Regular|Oblique|Medium|Bold|Italic|Roman|PSMT|MT)$", "", name)
    aliases = FONT_ALIASES.get(name)
    if aliases:
        return aliases
    if name in {"ArialMT", "Arial-BoldMT", "Arial-ItalicMT"}:
        return "Arial"
    if name in {"TimesNewRomanPSMT", "TimesNewRomanPS-BoldMT", "TimesNewRomanPS-ItalicMT"}:
        return "Times New Roman"
    return _xml_text(name)[:100] or ("Arial" if rtl else "Calibri")


def _run_for_span(paragraph, span: Span, selected: set[int]):
    link = span.link
    if isinstance(link, int) and link not in selected:
        link = None
    if link is None:
        return paragraph.add_run()
    container = _element("w:hyperlink", history=1)
    if isinstance(link, int):
        container.set(qn("w:anchor"), f"SourcePage{link}")
    else:
        relationship = paragraph.part.relate_to(link, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
        container.set(qn("r:id"), relationship)
    run_element = _element("w:r")
    container.append(run_element)
    paragraph._p.append(container)
    return Run(run_element, paragraph)


def _style_run(run, span: Span, scale: float, editable: bool) -> None:
    rtl = _rtl(span.text)
    font = run.font
    if editable:
        font.name = _font_name(span.font, rtl)
        font.size = Pt(max(5, min(112, span.size * scale)))
        font.color.rgb = RGBColor.from_string(f"{span.color & 0xFFFFFF:06X}")
        font.bold = bool(span.flags & pymupdf.TEXT_FONT_BOLD)
        font.italic = bool(span.flags & pymupdf.TEXT_FONT_ITALIC)
        if span.flags & pymupdf.TEXT_FONT_SUPERSCRIPT:
            font.superscript = True
    else:
        if span.flags & pymupdf.TEXT_FONT_BOLD:
            font.bold = True
        if span.flags & pymupdf.TEXT_FONT_ITALIC:
            font.italic = True
    if rtl:
        font.rtl = True
        if editable:
            properties = run._r.get_or_add_rPr()
            properties.rFonts.set(qn("w:cs"), font.name)
            _replace(properties, "w:szCs", val=round(font.size.pt * 2))
            if font.bold:
                _replace(properties, "w:bCs", val=1)
            if font.italic:
                _replace(properties, "w:iCs", val=1)
    if span.link is not None:
        font.underline = True
        if not editable or span.color == 0:
            font.color.rgb = RGBColor.from_string("1565AC")


class Numbering:
    """Attach explicit list numbering, including a source list's starting value."""

    def __init__(self, document) -> None:
        self.root = document.part.numbering_part.element
        self.abstract_ids: dict[str, int] = {}
        self.active: dict[tuple[str, int], tuple[int, int]] = {}

    def reset(self) -> None:
        self.active.clear()

    def _abstract_id(self, kind: str) -> int:
        if kind in self.abstract_ids:
            return self.abstract_ids[kind]
        ids = [int(node.get(qn("w:abstractNumId"))) for node in self.root.findall(qn("w:abstractNum"))]
        number = max(ids, default=-1) + 1
        abstract = _element("w:abstractNum", abstractNumId=number)
        abstract.append(_element("w:multiLevelType", val="multilevel"))
        for level in range(4):
            definition = _element("w:lvl", ilvl=level)
            definition.append(_element("w:start", val=1))
            definition.append(_element("w:numFmt", val=kind))
            definition.append(_element("w:lvlText", val="•" if kind == "bullet" else f"%{level + 1}."))
            definition.append(_element("w:lvlJc", val="left"))
            properties = _element("w:pPr")
            properties.append(_element("w:ind", left=300 + 420 * level, hanging=260))
            definition.append(properties)
            abstract.append(definition)
        first_instance = self.root.find(qn("w:num"))
        if first_instance is None:
            self.root.append(abstract)
        else:
            first_instance.addprevious(abstract)
        self.abstract_ids[kind] = number
        return number

    def apply(self, paragraph, item: Paragraph) -> int:
        text = item.lines[0].text
        if item.role == "bullet":
            match = BULLET.match(text)
            kind, start = "bullet", 1
        else:
            match = NUMBERED.match(text)
            if match is None:
                return 0
            token_match = LIST_PREFIX.search(match[0])
            if token_match is None:
                return 0
            token = token_match[0]
            if token.isdigit():
                kind, start = "decimal", int(token)
            else:
                kind = "upperLetter" if token.isupper() else "lowerLetter"
                start = ord(token.lower()) - ord("a") + 1
        if match is None:
            return 0
        key = (kind, item.list_level)
        previous = self.active.get(key)
        if previous and previous[1] == start:
            number = previous[0]
        else:
            instance = self.root.add_num(self._abstract_id(kind))
            instance.add_lvlOverride(item.list_level).add_startOverride(start)
            number = instance.numId
        self.active[key] = (number, start if kind == "bullet" else start + 1)
        properties = paragraph._p.get_or_add_pPr().get_or_add_numPr()
        properties.get_or_add_ilvl().val = item.list_level
        properties.get_or_add_numId().val = number
        return len(match[0])


@dataclass(frozen=True)
class Frame:
    origin: float
    width: float
    scale: float
    height: float


class WordWriter:
    def __init__(self, settings: dict, selected: list[int]) -> None:
        self.document = Document()
        self.settings = settings
        self.selected = {page + 1 for page in selected}
        self.mode = settings.get("mode", "editable")
        self.editable = self.mode == "editable"
        self.numbering = Numbering(self.document)
        self.signature: tuple | None = None
        self.last_page = 0
        self.pending_page: int | None = None
        self.page_break = False
        self.image_count = 0
        self.image_hashes: set[bytes] = set()
        self.image_bytes = 0
        self.table_count = 0
        self.warnings: list[str] = []
        self.document.core_properties.title = "Converted PDF"
        self.document.core_properties.author = "PDF to Word Pro"
        normal = self.document.styles["Normal"]
        normal.font.name = "Calibri"
        normal.font.size = Pt(11)
        normal.paragraph_format.space_after = Pt(6)

    def save(self, path: Path) -> None:
        self.document.save(path)

    def begin_page(self, layout: PageLayout) -> Frame:
        width, height = layout.width, layout.height
        if self.mode != "visual" and not self.settings.get("preserve_page_size", True):
            width, height = (792, 612) if width > height else (612, 792)
        paper_scale = min(1, MAX_WORD_POINTS / max(width, height))
        width, height = width * paper_scale, height * paper_scale
        scale = min(1, width / layout.width, height / layout.height)
        if max(layout.width, layout.height) > MAX_WORD_POINTS:
            self.warnings.append(f"Page {layout.number}: page dimensions were scaled to fit Word's maximum size.")

        if self.mode == "visual":
            left = right = top = bottom = 0.0
        elif self.editable and layout.contents and self.settings.get("preserve_page_breaks", True):
            origin = min(item.box.x0 for item in layout.contents) * scale
            end = max(item.box.x1 for item in layout.contents) * scale
            left = max(9, min(96, origin, width * 0.18))
            right = max(9, min(69, width - end, width * 0.18))
            top = max(12, min(85, min(item.box.y0 for item in layout.contents) * scale, height * 0.15))
            bottom = max(12, min(40, height * 0.09))
        else:
            left = right = max(8, min(54, width * 0.12))
            top = bottom = max(8, min(49, height * 0.11))
        if layout.headers:
            top = max(top, min(height * 0.2, max(item.box.y1 for item in layout.headers) * scale + 4))
        if layout.footers:
            bottom = max(bottom, min(height * 0.2, max(layout.height - item.box.y0 for item in layout.footers) * scale + 4))
        header_key = tuple(item.text for item in layout.headers)
        footer_key = tuple("PAGE" if item.role == "page-number" else item.text for item in layout.footers)
        numbered = "PAGE" in footer_key
        signature = tuple(round(value) for value in [width, height, left, right, top, bottom]) + (
            header_key, footer_key,
        )
        changed = signature != self.signature or (numbered and self.last_page + 1 != layout.number)
        section = self.document.sections[-1]
        if changed:
            if self.signature is not None:
                section = self.document.add_section(WD_SECTION.NEW_PAGE)
                self._compact(self.document.paragraphs[-1])
            section.orientation = WD_ORIENT.LANDSCAPE if width > height else WD_ORIENT.PORTRAIT
            section.page_width, section.page_height = Pt(width), Pt(height)
            section.left_margin, section.right_margin = Pt(left), Pt(right)
            section.top_margin, section.bottom_margin = Pt(top), Pt(bottom)
            section.header_distance = Pt(max(4, min(top - 8, min((item.box.y0 * scale for item in layout.headers), default=12))))
            section.footer_distance = Pt(
                max(4, min(bottom - 7, height - max((item.box.y1 * scale for item in layout.footers), default=height - 12)))
            )
            self._running(section, layout, left, width - left - right, scale, numbered)
            self.signature = signature

        self.pending_page = layout.number
        self.page_break = not changed and bool(self.last_page) and (
            self.mode == "visual" or self.settings.get("preserve_page_breaks", True)
        )
        self.last_page = layout.number
        self.numbering.reset()
        return Frame(left / scale, (width - left - right) / scale, scale, (height - top - bottom) / scale)

    def _running(self, section, layout: PageLayout, left: float, width: float, scale: float, numbered: bool) -> None:
        properties = section._sectPr
        previous = properties.find(qn("w:pgNumType"))
        if previous is not None:
            properties.remove(previous)
        if numbered:
            _replace(properties, "w:pgNumType", start=layout.number)
        frame = Frame(left / scale, width / scale, scale, layout.height)
        for container, items in [(section.header, layout.headers), (section.footer, layout.footers)]:
            if not items and container.is_linked_to_previous:
                if self.last_page:
                    container.is_linked_to_previous = False
                    self._compact(container.paragraphs[0])
                continue
            if items:
                container.is_linked_to_previous = False
                for index, item in enumerate(items):
                    paragraph = container.paragraphs[0] if index == 0 else container.add_paragraph()
                    if item.role == "page-number":
                        self._page_number(paragraph, item)
                    else:
                        self._paragraph_content(paragraph, item, frame, 0)

    def _page_number(self, paragraph, item: Paragraph) -> None:
        text = item.text.strip()
        match = PAGE_VALUE.fullmatch(text)
        if match is None:
            paragraph.add_run(_xml_text(text))
            return
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_after = Pt(0)
        if match[1]:
            paragraph.add_run(_xml_text(match[1]))
        field = _element("w:fldSimple", instr="PAGE")
        run = _element("w:r")
        content = _element("w:t")
        content.text = match[2]
        run.append(content)
        field.append(run)
        paragraph._p.append(field)
        if match[3]:
            paragraph.add_run(_xml_text(match[3]))

    @staticmethod
    def _compact(paragraph) -> None:
        properties = paragraph.paragraph_format
        properties.space_before, properties.space_after = Pt(0), Pt(0)
        properties.line_spacing = Pt(1)
        properties.keep_with_next = False
        paragraph.add_run().font.size = Pt(1)

    def _attach_page(self, paragraph) -> None:
        if self.pending_page is None:
            return
        _bookmark(paragraph, self.pending_page)
        if self.page_break:
            paragraph.paragraph_format.page_break_before = True
        self.pending_page = None

    def _placeholder(self) -> None:
        if self.pending_page is not None:
            paragraph = self.document.add_paragraph()
            self._compact(paragraph)
            self._attach_page(paragraph)

    def _alignment(self, paragraph, item: Paragraph, frame: Frame) -> None:
        relative_left = item.box.x0 - frame.origin
        relative_right = frame.origin + frame.width - item.box.x1
        format = paragraph.paragraph_format
        tolerance = max(6, frame.width * 0.034)
        if relative_left >= 8 and abs(relative_left - relative_right) <= tolerance:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif relative_left > frame.width * 0.26 and relative_right < tolerance:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        elif item.role not in {"bullet", "number"}:
            format.left_indent = Pt(max(0, relative_left) * frame.scale)
            if len(item.lines) > 1:
                format.right_indent = Pt(max(0, min(relative_right, frame.width * 0.27)) * frame.scale)
            first_indent = item.lines[0].box.x0 - item.box.x0
            if first_indent > 2:
                format.first_line_indent = Pt(first_indent * frame.scale)
        if item.role not in {"bullet", "number"} and paragraph.alignment is None and _rtl(item.text):
            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    def _paragraph_content(self, paragraph, item: Paragraph, frame: Frame, gap: float) -> None:
        if item.role.startswith("heading"):
            paragraph.style = "Heading 1" if item.role == "heading1" else "Heading 2"
        formatting = paragraph.paragraph_format
        if _rtl(item.text):
            _replace(paragraph._p.get_or_add_pPr(), "w:bidi", val=1)
        if self.editable:
            formatting.space_before = Pt(max(0, min(72, gap)) * frame.scale)
            formatting.space_after = Pt(0)
            formatting.keep_with_next = False
            formatting.widow_control = False
            if len(item.lines) > 1:
                baseline_gaps = [second.box.y0 - first.box.y0 for first, second in zip(item.lines, item.lines[1:])]
                valid_gaps = [distance for distance in baseline_gaps if distance > 0]
                if valid_gaps:
                    formatting.line_spacing = Pt(max(8, min(100, sum(valid_gaps) / len(valid_gaps) * frame.scale)))
            self._alignment(paragraph, item, frame)
        elif _rtl(item.text):
            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT

        strip = self.numbering.apply(paragraph, item) if item.role in {"bullet", "number"} else 0
        if item.role not in {"bullet", "number"}:
            self.numbering.reset()
        for index, line in enumerate(item.lines):
            if index:
                if self.editable:
                    paragraph.add_run().add_break()
                else:
                    paragraph.add_run(" ")
            for span in line.spans:
                text = span.text
                if strip:
                    prefix = min(strip, len(text))
                    text, strip = text[prefix:], strip - prefix
                text = _xml_text(text)
                if text:
                    run = _run_for_span(paragraph, span, self.selected)
                    run.text = text
                    _style_run(run, span, frame.scale, self.editable)

    def _picture(self, paragraph, item: Picture, frame: Frame, gap: float) -> None:
        identifier = sha256(item.data).digest()
        new_image = identifier not in self.image_hashes
        if new_image and self.image_bytes + len(item.data) > MAX_WORD_MEDIA_BYTES:
            if self.mode == "visual":
                raise EngineError("The selected visual pages exceed the Word image budget. Convert fewer pages at once.")
            self.warnings.append("Some pictures were omitted because the Word image budget was reached.")
            return
        formatting = paragraph.paragraph_format
        formatting.space_after = Pt(0)
        formatting.space_before = Pt(0 if self.mode == "visual" else max(0, min(54, gap)) * frame.scale)
        formatting.keep_with_next = False
        formatting.keep_together = False
        formatting.widow_control = False
        if self.mode == "visual":
            formatting.line_spacing = 1.0
        indent = max(0, item.box.x0 - frame.origin) if self.editable else 0
        formatting.left_indent = Pt(indent * frame.scale)
        fit = min(1, (max(5, frame.width - indent)) / item.box.width, (frame.height - 4) / item.box.height)
        if self.mode == "visual":
            # A few points leave room for Word's inline-image baseline and the section marker.
            fit = min(fit, (frame.height - 6) / item.box.height)
        try:
            run = paragraph.add_run()
            run.font.size = Pt(2)
            picture = run.add_picture(
                BytesIO(item.data), width=Pt(item.box.width * fit * frame.scale),
                height=Pt(item.box.height * fit * frame.scale),
            )
            picture._inline.docPr.set("descr", item.description)
            self.image_count += 1
            if new_image:
                self.image_hashes.add(identifier)
                self.image_bytes += len(item.data)
        except (UnrecognizedImageError, OSError, ValueError, RuntimeError, TypeError, IndexError):
            if self.mode == "visual":
                raise
            self.warnings.append(f"Page {self.last_page}: an image format could not be embedded in Word.")

    @staticmethod
    def _add_table(container, rows: int, widths: list[float], indent: float = 0.0):
        table = container.add_table(rows=rows, cols=len(widths))
        table.autofit = False
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        _replace(table._tbl.tblPr, "w:tblInd", w=round(indent * 20), type="dxa")
        for column, width in zip(table.columns, widths):
            column.width = Pt(width)
        for row in table.rows:
            for cell, width in zip(row.cells, widths):
                cell.width = Pt(width)
        return table

    def _table(self, container, item: Table, frame: Frame) -> None:
        self.numbering.reset()
        if container is self.document:
            self._placeholder()
        indent = max(0, min(frame.width * 0.45, item.box.x0 - frame.origin)) if self.editable else 0
        size = min(frame.width - indent, item.box.width) * frame.scale
        widths = [max(4, width / sum(item.widths) * size) for width in item.widths]
        table = self._add_table(container, len(item.rows), widths, indent * frame.scale)
        table.style = "Table Grid"
        for row_index, values in enumerate(item.rows):
            for column_index, text in enumerate(values):
                paragraph = table.cell(row_index, column_index).paragraphs[0]
                paragraph.paragraph_format.space_after = Pt(2)
                paragraph.paragraph_format.space_before = Pt(2)
                if _rtl(text):
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    _replace(paragraph._p.get_or_add_pPr(), "w:bidi", val=1)
                run = paragraph.add_run(_xml_text(text))
                run.font.size = Pt(9 if self.editable else 10)
                run.font.rtl = _rtl(text)
        for top, left, bottom, right in item.merges:
            table.cell(top, left).merge(table.cell(bottom, right))
        self.table_count += 1

    def _columns(self, item: Columns, frame: Frame) -> None:
        self._placeholder()
        bounds = [enclosing(group) for group in item.groups]
        edges = [frame.origin]
        for left, right in zip(bounds, bounds[1:]):
            edges.append((left.x1 + right.x0) / 2)
        edges.append(frame.origin + frame.width)
        if any(right - left < 24 for left, right in zip(edges, edges[1:])):
            for group in item.groups:
                self._render(self.document, group, frame, item.box.y0)
            return
        widths = [(right - left) * frame.scale for left, right in zip(edges, edges[1:])]
        table = self._add_table(self.document, 1, widths)
        borders = _element("w:tblBorders")
        for name in ("top", "left", "bottom", "right", "insideH", "insideV"):
            borders.append(_element(f"w:{name}", val="nil"))
        table._tbl.tblPr.append(borders)
        margins = _element("w:tblCellMar")
        for name in ("top", "left", "bottom", "right"):
            margins.append(_element(f"w:{name}", w=0, type="dxa"))
        table._tbl.tblPr.append(margins)
        for index, group in enumerate(item.groups):
            cell = table.cell(0, index)
            self._compact(cell.paragraphs[0])
            column = Frame(edges[index], widths[index] / frame.scale, frame.scale, frame.height)
            self._render(cell, group, column, item.box.y0)

    def _render(self, container, items: list[Element | Columns], frame: Frame, y: float) -> None:
        for item in items:
            gap = item.box.y0 - y
            if isinstance(item, Columns):
                if self.editable and self.settings.get("preserve_columns", True):
                    self._columns(item, frame)
                else:
                    for group in item.groups:
                        self._render(container, group, frame, y)
            elif isinstance(item, Table):
                self._table(container, item, frame)
            else:
                paragraph = container.add_paragraph()
                if container is self.document:
                    self._attach_page(paragraph)
                if isinstance(item, Picture):
                    self._picture(paragraph, item, frame, gap)
                else:
                    self._paragraph_content(paragraph, item, frame, gap)
            y = max(y, item.box.y1)

    def write_page(self, layout: PageLayout) -> None:
        frame = self.begin_page(layout)
        section = self.document.sections[-1]
        self._render(self.document, order_elements(layout), frame, section.top_margin.pt / frame.scale)
        self._placeholder()
