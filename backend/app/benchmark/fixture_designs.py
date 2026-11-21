"""Original PDF drawing recipes and ground truth recorded before extraction."""

from collections import Counter
from dataclasses import dataclass, field
from html import escape
from io import BytesIO
from math import cos, pi, sin

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
import pymupdf as fitz

from .fixture_catalog import Case

BLUE = (0.12, 0.24, 0.42)
INK = (0.12, 0.16, 0.21)
GRAY = (0.37, 0.43, 0.49)
LIGHT = (0.87, 0.92, 0.96)
RULE = (0.57, 0.66, 0.74)
FONT_NAMES = {
    "helv": "Helvetica",
    "hebo": "Helvetica-Bold",
    "heit": "Helvetica-Oblique",
    "tiro": "Times-Roman",
    "tibo": "Times-Bold",
    "tiit": "Times-Italic",
    "cour": "Courier",
    "cobo": "Courier-Bold",
}
LANG_TAG = {"eng": "en", "urd": "ur", "ara": "ar", "spa": "es", "fra": "fr", "deu": "de", "jpn": "ja"}
FEATURE_KEYS = {
    "heading": "headings",
    "list": "lists",
    "header": "headers",
    "footer": "footers",
    "page-number": "page_numbers",
    "footnote": "footnotes",
}
REGION_KEYS = {"header", "footer", "page-number"}

LANGUAGE_TEXT = {
    "ara": (
        "هذا مستند عربي لاختبار قراءة النص وتحويله إلى ملف جديد",
        "تحتوي هذه الصفحة على ملاحظات أصلية عن أعمال المختبر",
        "تراجع اللجنة الوثيقة صباح يوم الاثنين وتكتب تقريرا واضحا",
        "ترسل النسخة النهائية إلى فريق الجودة بعد مراجعة النتائج",
    ),
    "urd": (
        "یہ اردو دستاویز متن کی شناخت اور تبدیلی کے لیے ہے",
        "یہ صفحہ تجربہ گاہ کے کام کی اصل تفصیلات پیش کرتا ہے",
        "ٹیم پیر کی صبح رپورٹ کو دوبارہ پڑھ کر نتائج لکھے گی",
        "معیار کی جانچ کے بعد رپورٹ کی نقل دفتر میں بھیجی جائے گی",
    ),
    "fra": ("Échantillon de qualité contrôlée.", "Le relevé vérifié décrit une série de mesures."),
    "spa": ("Evaluación técnica del envío número doce.", "La revisión reúne métricas y señales válidas."),
    "deu": ("Prüfung der Größe und der verfügbaren Maße.", "Die Übersicht enthält gültige Einträge."),
    "jpn": ("文書変換の品質を確認します。", "実験結果を記録します。"),
    "eng": ("The sample was prepared for testing.", "Reviewers record measurements in the project register."),
}


def box_values(rect) -> list[float]:
    return [round(float(value), 3) for value in rect]


@dataclass(slots=True)
class Sheet:
    page: fitz.Page
    blocks: list[dict] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    table_boxes: list[list[float]] = field(default_factory=list)
    images: list[list[float]] = field(default_factory=list)
    features: Counter = field(default_factory=Counter)
    links: list[dict] = field(default_factory=list)
    fonts: set[str] = field(default_factory=set)

    def record(self, text: str, box, role: str, font: str | None = None) -> None:
        entry = {"text": text, "bbox": box_values(box), "role": role}
        if font:
            entry["font"] = font
            self.fonts.add(font)
        self.blocks.append(entry)
        key = FEATURE_KEYS.get(role)
        if key:
            self.features[key] += 1

    def line(
        self, text: str, x: float, y: float, *, size: float = 12, font: str = "helv",
        color=INK, role: str = "body",
    ) -> fitz.Rect:
        self.page.insert_text((x, y), text, fontname=font, fontsize=size, color=color)
        metrics = fitz.Font(fontname=font)
        box = fitz.Rect(x, y - metrics.ascender * size, x + metrics.text_length(text, fontsize=size), y - metrics.descender * size)
        self.record(text, box, role, FONT_NAMES[font])
        return box

    def heading(self, text: str, y: float = 74, *, x: float = 48, size: float = 22) -> None:
        self.line(text, x, y, size=size, font="hebo", color=BLUE, role="heading")

    def html_line(
        self, text: str, x: float, y: float, width: float, *, language: str = "eng", size: float = 16,
        role: str = "body",
    ) -> None:
        direction = "rtl" if language in {"ara", "urd"} else "ltr"
        block = fitz.Rect(x, y, x + width, y + size * 2.4)
        result, _ = self.page.insert_htmlbox(
            block,
            f'<div dir="{direction}" lang="{LANG_TAG[language]}">{escape(text)}</div>',
            css=f"body, div {{ margin:0; font-size:{size}pt; color:#182936; }}",
        )
        if result < 0:
            raise RuntimeError("Authored multilingual fixture text exceeds its frame.")
        # The Story frame is independently laid out. The occupied height is
        # derived from placement geometry, never from extracted Word or PDF text.
        self.record(text, (x, y, x + width, block.y1 - result), role)
        if direction == "rtl":
            self.features["rtl"] += 1

    def raster(self, rect: fitz.Rect, content: bytes) -> None:
        self.page.insert_image(rect, stream=content, keep_proportion=False)
        self.images.append(box_values(rect))

    def link(self, label: str, x: float, y: float, destination: dict) -> None:
        bounds = self.line(label, x, y, color=(0.05, 0.26, 0.60), role="hyperlink")
        self.page.insert_link({"from": bounds, **destination})
        self.links.append({
            "text": label,
            "bbox": box_values(bounds),
            "target": destination.get("uri") or f"page:{destination['page'] + 1}",
        })
        self.features["hyperlinks"] += 1

    def truth(
        self, *, languages: tuple[str, ...], ocr_required: bool, width: float, height: float,
        rotation: int = 0, skew: float = 0, dpi: int | None = None,
    ) -> dict:
        def text_for(regions: set[str], *, include: bool = True) -> str:
            return "\n".join(block["text"] for block in self.blocks if (block["role"] in regions) == include)

        def transformed(rect) -> list[float]:
            points = [(rect[i], rect[j]) for i in (0, 2) for j in (1, 3)]
            cx, cy = width / 2, height / 2
            radians = skew * pi / 180
            if skew:
                points = [
                    (cx + cos(radians) * (x - cx) + sin(radians) * (y - cy),
                     cy - sin(radians) * (x - cx) + cos(radians) * (y - cy))
                    for x, y in points
                ]
            if rotation == 90:
                points = [(height - y, x) for x, y in points]
            elif rotation == 180:
                points = [(width - x, height - y) for x, y in points]
            elif rotation == 270:
                points = [(y, width - x) for x, y in points]
            xs, ys = zip(*points, strict=True)
            return box_values((min(xs), min(ys), max(xs), max(ys)))

        if rotation in (90, 270):
            page_width, page_height = height, width
        else:
            page_width, page_height = width, height
        return {
            "text": "\n".join(block["text"] for block in self.blocks),
            "body_text": text_for(REGION_KEYS, include=False),
            "header_text": text_for({"header"}),
            "footer_text": text_for({"footer", "page-number"}),
            "width": page_width,
            "height": page_height,
            "rotation": rotation,
            "tables": self.tables,
            "table_boxes": [transformed(box) for box in self.table_boxes],
            "images": [transformed(box) for box in self.images],
            "blocks": [{**block, "bbox": transformed(block["bbox"])} for block in self.blocks],
            "links": [{**link, "bbox": transformed(link["bbox"])} for link in self.links],
            "fonts": sorted(self.fonts),
            "languages": list(languages),
            "ocr_required": ocr_required,
            "scan_background": dpi is not None,
            "scan": {"dpi": dpi, "skew_degrees_counterclockwise": skew, "rotation_degrees_clockwise": rotation} if dpi else None,
        }


def authored_image(seed: int, *, kind: str = "photograph") -> bytes:
    """Generate original deterministic raster artwork from seeded geometry and color."""
    if kind in {"alpha", "logo"}:
        image = Image.new("RGBA", (420, 210), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        shift = seed % 23
        draw.rounded_rectangle((23, 54, 393, 158), radius=31, fill=(25, 66, 94, 224))
        draw.polygon(((51, 123), (116, 67), (170, 123), (224, 80), (270, 123)), fill=(100, 218, 202, 223))
        draw.ellipse((300, 65 + shift, 340, 106 + shift), fill=(250, 187, 94, 248))
    else:
        rng = np.random.default_rng(seed)
        width, height = 480, 256
        y, x = np.indices((height, width), dtype=np.float32)
        horizon = 112 + 15 * np.sin(x / 53 + seed / 3)
        cloud = 7 * np.sin(x / 33 + y / 12) + 5 * np.cos(x / 77 - y / 19)
        noise = rng.normal(0, 2.5, (height, width))
        emissive = 30 * np.exp(-((x - (90 + seed % 240)) ** 2 + (y - 61) ** 2) / 4300)
        sky = np.stack((64 + 0.48 * y, 130 + 0.28 * y, 168 + 0.19 * y), axis=-1)
        field_color = np.stack((54 + .22 * y, 94 + .25 * y, 66 + .13 * y), axis=-1)
        mist = (cloud + noise + emissive)[..., None]
        image_data = np.where((y < horizon)[..., None], sky + mist, field_color + mist * .7)
        image = Image.fromarray(np.clip(image_data, 0, 255).astype(np.uint8))
        draw = ImageDraw.Draw(image)
        for offset, height_delta in ((0, 0), (117, 5), (169, -6), (288, 10)):
            px = 45 + (seed + offset) % 360
            py = 144 + height_delta
            draw.polygon(((px - 16, py + 20), (px, py - 12), (px + 19, py + 20)), fill=(58, 77, 75))
        image = image.filter(ImageFilter.GaussianBlur(.40))
        if kind == "gray-art":
            image = image.convert("L")
    output = BytesIO()
    if image.mode == "RGBA":
        image.save(output, format="PNG", optimize=True)
    else:
        image.save(output, format="JPEG", quality=82, optimize=True)
    return output.getvalue()


def _basic(sheet: Sheet, index: int, number: int) -> None:
    sheet.heading(f"Blue Harbor records {number:03}")
    sheet.line(f"Reference sheet {index + 1}", 48, 119, font="tiro")
    sheet.line("This record summarizes measurements from the North Pier.", 48, 150, font="tiro")
    sheet.line("Staff review the equipment before preparing the final report.", 48, 171, font="tiro")
    sheet.line(f"Sample marker: BH-{number:03}-{index + 1:03}.", 48, 212, size=11, font="cour", color=GRAY)


def _paragraphs(sheet: Sheet, index: int, number: int) -> None:
    sheet.heading(f"Incident summary {number:03}")
    paragraphs = [
        ("Operations staff checked the pier at dawn.", "They recorded wind and water measurements in the daily ledger.",
         "The initial equipment readings satisfied the published tolerance."),
        ("A second team visited after lunch.", "Their report describes the inspection and the order of decisions.",
         "Reviewers compared the new measurements with earlier records."),
        ("The signed finding appears on the last worksheet.", "An independent reviewer matched the docket number to the index.",
         f"This page records observation {index + 4} from the ongoing survey."),
    ]
    for row, lines in enumerate(paragraphs):
        for line, text in enumerate(lines):
            sheet.line(text, 54 + 8 * (row % 2), 115 + row * 89 + line * 18, font="tiro")
    sheet.line("End of field notes.", 54, 400, font="tiit", color=GRAY)


def _running(sheet: Sheet, index: int, number: int, *, large: bool = False) -> None:
    sheet.line("BLUE HARBOR QUALITY LAB", 48, 35, size=10, font="hebo", role="header")
    sheet.page.draw_line((48, 43), (sheet.page.rect.width - 48, 43), color=RULE, width=.65)
    if large:
        _large(sheet, index, number)
    else:
        _basic(sheet, index, number)
    baseline = sheet.page.rect.height - 33
    sheet.line("Original test material", 48, baseline, size=9, role="footer")
    sheet.line(str(index + 1), sheet.page.rect.width - 61, baseline, size=10, role="page-number")


def _columns(sheet: Sheet, number: int, count: int, *, index: int = 0) -> None:
    width = sheet.page.rect.width
    sheet.heading(f"Monitoring review {number:03}")
    first = len(sheet.blocks)
    columns = []
    ordinal = ("Left", "Center", "Right") if count == 3 else ("Left", "Right")
    for column in reversed(range(count)):
        x = 48 + column * ((width - 96) / count)
        start = len(sheet.blocks)
        sheet.heading(f"{ordinal[column]} notes", 123, x=x, size=13)
        for row, body in enumerate((
            f"{ordinal[column]} {index + 1}: initial survey",
            "The pier staff checked tide marks.",
            "Reviewers transcribed observations.",
            "The summary entered the docket.",
        )):
            sheet.line(body, x, 155 + row * 33 + 3 * column, size=9.6, font="tiro")
        columns.append(sheet.blocks[start:])
    sheet.blocks[first:] = [block for column in reversed(columns) for block in column]


def _sidebar(sheet: Sheet, number: int, index: int) -> None:
    sheet.heading(f"Planning brief {number:03}")
    sheet.page.draw_rect((48, 109, 193, 349), color=None, fill=LIGHT)
    sheet.heading("At a glance", 137, x=62, size=13)
    sheet.line(f"Report group {index + 1}", 62, 169, size=10)
    sheet.line("Window: afternoon", 62, 191, size=10)
    sheet.line("Review: complete", 62, 213, size=10)
    sheet.heading("Observations", 126, x=223, size=16)
    for row, body in enumerate((
        "Crews inspected the north and west stations.",
        "The team logged instrument readings in sequence.",
        "A sealed container held replacement fittings.",
        "Recorded results were transferred to the summary.",
    )):
        sheet.line(body, 223 + (12 if row == 2 else 0), 157 + row * 30, size=11, font="tiro")
    sheet.line("Revision entry archived.", 48, 397, size=10, color=GRAY)


def _grid(
    sheet: Sheet, x: float, y: float, width: float, rows: list[list[str]], *, variant: str = "grid", size: float = 10,
) -> None:
    columns = len(rows[0])
    weights = [3, *([2] * (columns - 1))] if variant in {"complex-grid", "wrapped", "merged"} else [1] * columns
    positions = [x + width * sum(weights[:i]) / sum(weights) for i in range(columns + 1)]
    row_heights = [34 if any("\n" in cell for cell in row) else 25 for row in rows]
    bounds = [y + sum(row_heights[:i]) for i in range(len(rows) + 1)]
    if variant != "borderless":
        sheet.page.draw_rect((x, y, x + width, bounds[1]), color=None, fill=LIGHT)
        if variant == "finance":
            sheet.page.draw_rect((x, bounds[-2], x + width, bounds[-1]), color=None, fill=(.90, .95, .85))
        for column, horizontal in enumerate(positions):
            top = bounds[1] if variant == "merged" and 0 < column < columns else y
            sheet.page.draw_line((horizontal, top), (horizontal, bounds[-1]), color=GRAY, width=.65)
        for vertical in bounds:
            sheet.page.draw_line((x, vertical), (x + width, vertical), color=GRAY, width=.65)
    for row_index, row in enumerate(rows):
        for column, value in enumerate(row):
            for line_index, line in enumerate(value.splitlines()):
                if line:
                    sheet.line(
                        line, positions[column] + 6, bounds[row_index] + 16 + 12 * line_index,
                        size=size, font="hebo" if row_index == 0 else "helv", role="table",
                    )
    sheet.tables.append(rows)
    sheet.table_boxes.append(box_values((x, y, x + width, bounds[-1])))


def _table(sheet: Sheet, number: int, design: str, index: int, *, with_heading: bool = True) -> None:
    if with_heading:
        sheet.heading(f"{'Harbor services invoice' if design == 'invoice' else 'Inspection matrix'} {number:03}")
        sheet.line(f"Prepared for the sample project. Review sequence {index + 1}.", 48, 112)
    width = sheet.page.rect.width - 96
    if design == "invoice":
        rows = [["Service", "Units", "Amount"], ["Survey", "2", "140.00"],
                ["Calibration", "1", "85.00"], ["Total", "3", "225.00"]]
    elif design == "finance":
        base = number * 73 + index
        rows = [["Program", "Previous", "Current", "Difference"]]
        rows += [[name, f"{base + offset:.2f}", f"{base + offset + 80:.2f}", "80.00"]
                 for name, offset in (("Marine", 406), ("Harbor", 145), ("Reserve", 237), ("Total", 788))]
    elif design == "wide-grid":
        rows = [["Asset", "Owner", "Zone", "Check", "Code", "Status", "Count"]]
        rows += [[f"Pump {i}", "Survey", "West", "2026-01", f"BH-{i}", "Final", str(22 + i)] for i in range(1, 6)]
    elif design == "rubric":
        rows = [["Criterion", "Baseline", "Recheck", "Points"]]
        rows += [[name, "Recorded", "Reviewed", str(index + points)] for name, points in (
            ("Accuracy", 4), ("Completeness", 6), ("Readability", 5), ("Traceability", 7))]
    elif design == "technical-grid":
        rows = [["Field", "Type", "Required"], ["check.id", "string", "yes"],
                ["page_index", "integer", "yes"], ["verify._flags", "array", "no"]]
    else:
        rows = [["Item", "Condition", "Code", "Quantity"], ["Light tower", "Ready", "A8", "14"],
                ["Dock marker", "Review", "E3", "28"], ["Survey scale", "Ready", "S4", "12"],
                ["Reserve lock", "Archived", "W1", "9"]]
        if design == "wrapped":
            rows[1][1] = "Ready after\nnew inspection"
            rows[2][0] = "Dock marker\nassembly"
        elif design == "merged":
            rows.insert(0, ["Regional inspection worksheet", "", "", ""])
        elif design == "empty-cells":
            rows[2][1] = rows[3][2] = ""
    _grid(sheet, 48, 156 if with_heading else 365, width, rows, variant=design)
    if design == "double-grid":
        sheet.heading("Calibration notes", 333, size=14)
        _grid(sheet, 48, 353, width * .76, [["Tool", "Check"], ["Scale", "Verified"], ["Gauge", "Revised"]])


def _art(sheet: Sheet, number: int, design: str, index: int) -> None:
    sheet.heading(f"North Pier visual review {number:03}")
    sheet.line(f"Plate {index + 1} depicts original synthetic project material.", 48, 112)
    width = sheet.page.rect.width - 96
    if design in {"charts", "chart-gallery"}:
        chart_right = 48 + width * .9
        sheet.page.draw_line((58, 302), (chart_right, 302), color=GRAY)
        sheet.page.draw_line((58, 150), (58, 302), color=GRAY)
        points = []
        for bar, label in enumerate(("North", "East", "West", "South", "Reserve")):
            x = 79 + bar * (width - 55) / 5
            height = 47 + ((number + index * 17 + bar * 21) % 74)
            sheet.page.draw_rect((x, 302 - height, x + 31, 302), color=None, fill=BLUE)
            sheet.line(label, x - 3, 320, size=9, role="chart-label")
            sheet.line(str(height), x + 4, 291 - height, size=9, role="chart-label")
            points.append((x + 15, 277 - height))
        sheet.page.draw_polyline(points, color=(.70, .32, .20), width=1.2)
        sheet.features["vector_graphics"] += 1
    if design in {"diagram", "legend"}:
        sheet.page.draw_rect((68, 158, 255, 298), color=GRAY, width=1.1, fill=LIGHT)
        sheet.page.draw_circle((161, 229), 41, color=BLUE, width=1.3)
        sheet.page.draw_line((202, 229), (418, 229), color=GRAY, dashes="[3 2] 0")
        sheet.line("48 mm housing", 280, 216, size=11, role="diagram-label")
        sheet.line("Central meridian", 280, 251, size=11, role="diagram-label")
        sheet.features["vector_graphics"] += 1
    if design in {"photographs", "alpha", "gallery", "gray-art", "legend", "logo", "chart-gallery"}:
        y = 350 if design in {"chart-gallery", "legend"} else 147
        height = 84 if design in {"logo", "legend"} else 147
        image_width = 168 if design in {"logo", "legend"} else min(width, 360)
        destination = fitz.Rect(48, y, 48 + image_width, y + height)
        if design == "alpha":
            sheet.page.draw_rect(destination, color=None, fill=LIGHT)
        sheet.raster(destination, authored_image(number + index, kind=design))
        sheet.line("Figure A. Harbor reference view.", 48, y + height + 25, font="tiit", size=11)
    if design in {"photographs", "gallery"}:
        sheet.raster(fitz.Rect(80, 353, 80 + min(width - 32, 300), 478), authored_image(number + 31 + index))
        sheet.line("Figure B. Separate camera position.", 80, 503, font="tiit", size=11)


def _fonts(sheet: Sheet, number: int) -> None:
    sheet.heading(f"Typography review {number:03}", size=25)
    samples = (
        ("Serif body text uses Times.", "tiro", 12),
        ("Italic serif identifies an observation.", "tiit", 14),
        ("Bold labels precede the measurements.", "tibo", 16),
        ("Sans serif prose conveys the control value.", "helv", 11),
        ("Oblique text communicates the exception.", "heit", 13),
        ("Monospaced text: BH-42-LAB.", "cour", 11),
        ("Large monospaced header", "cobo", 19),
    )
    for row, (text, font, size) in enumerate(samples):
        sheet.line(text, 48 + (row % 3) * 9, 123 + row * 39, size=size, font=font, color=BLUE if row % 3 == 0 else INK)


def _technical(sheet: Sheet, number: int, index: int, design: str) -> None:
    sheet.heading(f"Laboratory note {number:03}")
    if design == "footnotes":
        sheet.line("Coastal measurements were taken at low tide.", 48, 148, font="tiro")
        partner = sheet.line("Reference datum recorded here", 48, 184, font="tiro")
        sheet.line("1", partner.x1 + 2, 178, font="tiro", size=7, role="footnote-marker")
        sheet.page.draw_line((48, 465), (195, 465), color=RULE)
        sheet.line("1 The reference datum was reset after the monthly review.", 48, 485, font="tiro", size=9, role="footnote")
    elif design == "math":
        for row, expression in enumerate((
            "E = m·c²", "σ = √(Σ (xᵢ − μ)² / n)", "A = πr²", "H₂O at 23 °C", "Δt = 0.75 μs",
        )):
            sheet.html_line(expression, 65, 118 + row * 42, 440, size=16, role="equation")
    elif design == "shortcuts":
        for row, label in enumerate(("Ctrl+Shift+Name", "Measure [north / east]", "save_pattern('x-y')", "Units: {m, mm, km}")):
            sheet.line(label, 52, 131 + row * 33, size=11, font="cour")
    else:
        sheet.line(f"Run notes for observation {index + 1}.", 48, 111)
        sheet.page.draw_rect((48, 140, sheet.page.rect.width - 48, 266), color=None, fill=LIGHT)
        program = ("def read_marker(record):", "    heading = record.get('marker')",
                   "    if heading is None:", "        return 'unassigned'", "    return heading.strip()")
        for row, line in enumerate(program):
            sheet.line(line, 62, 162 + row * 19, size=11, font="cour", role="code")
        sheet.line("The original spacing encodes the nesting level.", 48, 304)


def _rtl(sheet: Sheet, languages: tuple[str, ...], *, size: float = 19) -> None:
    frame = sheet.page.rect.width - 96
    top = 106
    for language in languages:
        if language == "eng":
            sheet.line("Delivery record for the North Pier.", 48, top + 18, size=14)
            top += 37
            continue
        content = LANGUAGE_TEXT[language]
        selected = content if len(languages) == 1 else content[:2]
        for row, text in enumerate(selected):
            sheet.html_line(text, 48, top, frame, language=language, size=size if row else size + 2, role="body")
            top += 39


def _form(sheet: Sheet, number: int, design: str) -> None:
    sheet.heading(f"Preparation checklist {number:03}")
    sheet.line("Original form template for field reviewers.", 48, 112)
    if design == "signed":
        sheet.line("Sampling and laboratory checks complete.", 48, 161, font="tiro")
        sheet.line("Approval signature field", 48, 220)
        widget = fitz.Widget()
        widget.field_type = fitz.PDF_WIDGET_TYPE_SIGNATURE
        widget.field_name = "BenchmarkSignature"
        widget.rect = fitz.Rect(48, 232, 317, 278)
        sheet.page.add_widget(widget)
        sheet.features["signatures"] += 1
        return
    form_fields = (
        (("Reviewer", fitz.PDF_WIDGET_TYPE_TEXT, "Lab technician"), ("Verified", fitz.PDF_WIDGET_TYPE_CHECKBOX, "Yes"))
        if design == "form" else
        (("Calibration completed", fitz.PDF_WIDGET_TYPE_CHECKBOX, "Yes"),
         ("Follow-up required", fitz.PDF_WIDGET_TYPE_CHECKBOX, "Off"))
    )
    for index, (label, field_type, value) in enumerate(form_fields):
        y = 159 + index * 60
        sheet.line(label, 48, y)
        widget = fitz.Widget()
        widget.field_type = field_type
        widget.field_name = f"value_{index}"
        widget.field_value = value
        widget.rect = fitz.Rect(247, y - 17, 400 if field_type == fitz.PDF_WIDGET_TYPE_TEXT else 266, y + 5)
        widget.border_color = BLUE
        widget.border_width = 1
        sheet.page.add_widget(widget)
        if field_type == fitz.PDF_WIDGET_TYPE_TEXT:
            sheet.record(value, widget.rect, "form-value")
        sheet.features["form_fields"] += 1


def _annotate(sheet: Sheet, number: int) -> None:
    sheet.heading(f"Editorial review {number:03}")
    box = sheet.line("Highlight the discrepancy in the final measurement chart.", 48, 133, font="tiro")
    sheet.page.add_highlight_annot(box)
    sheet.page.add_text_annot((460, 151), "Check the final value during review.")
    sheet.line("The visible prose belongs to the inspection record.", 48, 179, font="tiro")
    sheet.features["annotations"] += 2


def _scan_page(sheet: Sheet, number: int, index: int, design: str) -> None:
    if design == "table-scan":
        _table(sheet, number, "invoice", index)
        return
    sheet.heading(f"Blue Harbor Certificate {number:03}", 135, x=52, size=23)
    if design == "sparse-scan":
        sheet.line("Inspection approved.", 67, 358, size=17, font="hebo")
        return
    lines = (
        "The document was created for testing.",
        f"Original sample number {4827 + number + index}",
        "Please record the findings in a written report.",
        "Editable words follow the original reading order.",
        "A laboratory clerk reviewed the reference.",
    )
    if design in {"inverted-scan", "rotate-scan"}:
        lines += ("The committee reviewed the completed report.", "Sampling took place during the summer survey.",
                  "Inspectors recorded equipment readings on paper.", "Archive the original report with the field notes.")
    for row, line in enumerate(lines):
        sheet.line(line, 57, 189 + row * 36, size=16)


def _large(sheet: Sheet, index: int, number: int) -> None:
    sheet.heading(f"Field manual {number:03} · record {index + 1}", size=17)
    sheet.line(f"Survey station {index + 1} entered the North Pier register.", 48, 128, font="tiro")
    sheet.line(f"Control number BH-{number:03}-{index + 1:03}.", 48, 161, size=10, font="cour")


def draw_sheet(sheet: Sheet, case: Case, number: int, index: int, *, scanned: bool) -> None:
    design = case.design
    if design in {"blank", "running-blank"} and index == (1 if design == "blank" else 2):
        return
    if design in {"rtl", "mixed-script", "rtl-scan", "rtl-skew", "rtl-noise", "mixed-script-scan", "latin-script", "cjk", "mixed-language-pages"}:
        languages = case.languages if design != "mixed-language-pages" else (case.languages[index],)
        _rtl(sheet, languages)
    elif scanned:
        _scan_page(sheet, number, index, design)
    elif design in {"running", "running-blank", "large-running"}:
        _running(sheet, index, number, large=design == "large-running")
    elif design in {"large", "large-table", "large-images", "page-limit"}:
        _large(sheet, index, number)
        if design == "large-table" and index % 12 == 0:
            _table(sheet, number, "rubric", index, with_heading=False)
        if design == "large-images" and index % 4 == 0:
            sheet.raster(fitz.Rect(52, 195, 344, 341), authored_image(number + index))
            sheet.line("Original illustrated guide plate.", 52, 365, font="tiit")
    elif design in {"columns", "three-columns", "composite"}:
        _columns(sheet, number, 3 if design == "three-columns" else 2, index=index)
        if design == "composite":
            _table(sheet, number, "rubric", index, with_heading=False)
            sheet.raster(fitz.Rect(48, 530, 210, 600), authored_image(number + index))
            sheet.line("Equipment label for the sample lot.", 48, 628, font="tiit")
    elif design in {"invoice", "complex-grid", "finance", "wide-grid", "borderless", "rubric",
                    "merged", "wrapped", "empty-cells", "double-grid", "technical-grid"}:
        _table(sheet, number, design, index)
    elif design in {"charts", "photographs", "diagram", "alpha", "gallery", "gray-art", "legend", "logo", "chart-gallery"}:
        _art(sheet, number, design, index)
    elif design == "fonts":
        _fonts(sheet, number)
    elif design in {"math", "footnotes", "code", "shortcuts"}:
        _technical(sheet, number, index, design)
    elif design in {"form", "checkboxes", "signed"}:
        _form(sheet, number, design)
    elif design == "annotation":
        _annotate(sheet, number)
    elif design == "links":
        _basic(sheet, index, number)
        sheet.link("Project source materials", 48, 252, {"kind": fitz.LINK_URI, "uri": "https://example.org/benchmark"})
        sheet.link("Go to the next record", 48, 296, {"kind": fitz.LINK_GOTO, "page": (index + 1) % case.pages})
    elif design == "lists":
        sheet.heading(f"Review tasks {number:03}")
        entries = ((48, "1. Prepare the survey kit"), (68, "a. Clean each sensor"), (68, "b. Confirm the battery"),
                   (48, "2. Record and review"), (68, "• Read the station log"), (68, "• File the reviewed copy"))
        for row, (x, label) in enumerate(entries):
            sheet.line(label, x, 126 + row * 29, role="list")
    elif design == "sidebar":
        _sidebar(sheet, number, index)
    elif design in {"paragraphs", "insets"}:
        _paragraphs(sheet, index, number)
    elif design == "poster":
        title = "Public sampling notice"
        length = fitz.get_text_length(title, fontname="hebo", fontsize=28)
        sheet.heading(title, 107, x=(sheet.page.rect.width - length) / 2, size=28)
        sheet.line("Staff will inspect the east gate at 10 AM.", 123, 163, size=17, font="tibo")
        sheet.line("Please follow posted directions from the field team.", 145, 214, size=12)
        sheet.line("Original sample notice, quality laboratory archive.", 173, 515, size=8, color=GRAY)
    elif design in {"narrow", "small"}:
        sheet.heading(f"Inspection label {number:03}", 59, x=27, size=16)
        sheet.line("The review was recorded.", 27, 105, size=11, font="tiro")
        sheet.line(f"Docket BH-{number:03}", 27, 143, size=10, font="cour")
    else:
        _basic(sheet, index, number)


def degraded_scan(
    page: fitz.Page, *, dpi: int, skew: float, degradation: str, seed: int,
) -> bytes:
    pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
    image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
    if skew:
        image = image.rotate(skew, resample=Image.Resampling.BICUBIC, fillcolor=255)
    if degradation in {"noisy-scan", "rtl-noise"}:
        rng = np.random.default_rng(seed)
        data = np.asarray(image, dtype=np.int16)
        noise = rng.normal(0, 11, data.shape).astype(np.int16)
        image = Image.fromarray(np.clip(data + noise, 0, 255).astype(np.uint8))
    elif degradation == "faded-scan":
        image = ImageEnhance.Contrast(image).enhance(.30)
        image = image.filter(ImageFilter.GaussianBlur(.6))
    elif degradation in {"low-scan", "mixed-dpi"} and dpi < 100:
        image = image.filter(ImageFilter.GaussianBlur(.24))
    output = BytesIO()
    if degradation in {"noisy-scan", "rtl-noise", "low-scan", "mixed-dpi"}:
        image.save(output, format="JPEG", quality=79, optimize=True, dpi=(dpi, dpi))
    else:
        image.save(output, format="PNG", optimize=True, dpi=(dpi, dpi))
    return output.getvalue()
