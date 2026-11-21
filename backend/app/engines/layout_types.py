"""Editable elements recovered from one PDF page."""

from dataclasses import dataclass, field

import pymupdf

Rect = pymupdf.Rect


@dataclass
class Span:
    text: str
    box: Rect
    size: float
    font: str = ""
    flags: int = 0
    color: int = 0
    link: str | int | None = None


@dataclass
class Line:
    box: Rect
    spans: list[Span]

    @property
    def text(self) -> str:
        return "".join(span.text for span in self.spans)


@dataclass
class Paragraph:
    box: Rect
    lines: list[Line]
    role: str = ""
    list_level: int = 0

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines)


@dataclass
class Picture:
    box: Rect
    data: bytes
    description: str = "Image from the source PDF"


@dataclass
class Table:
    box: Rect
    rows: list[list[str]]
    widths: list[float]
    merges: list[tuple[int, int, int, int]] = field(default_factory=list)


Element = Paragraph | Picture | Table


@dataclass
class Columns:
    box: Rect
    groups: list[list[Element]]


@dataclass
class PageLayout:
    number: int
    width: float
    height: float
    kind: str
    contents: list[Element] = field(default_factory=list)
    headers: list[Paragraph] = field(default_factory=list)
    footers: list[Paragraph] = field(default_factory=list)
    body_size: float = 11
    source_rotation: int = 0
    ocr_confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
