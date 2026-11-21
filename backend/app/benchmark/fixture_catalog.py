"""Stable identities and authored variation for the initial benchmark corpus."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Case:
    title: str
    category: str
    design: str
    pages: int = 1
    languages: tuple[str, ...] = ("eng",)
    rejection: str | None = None


CASES = (
    Case("Simple one-page correspondence", "digital", "letter"),
    Case("Ten-page sample handbook", "digital", "handbook", 10),
    Case("Two-column academic brief", "complex-layout", "columns"),
    Case("Complex equipment inventory table", "tables", "complex-grid"),
    Case("Itemized service invoice", "tables", "invoice"),
    Case("Quarterly financial report with comparative values", "tables", "finance", 3),
    Case("Vector column and line charts", "images", "charts"),
    Case("Original synthetic landscape photographs", "images", "photographs"),
    Case("Running headers, footers, and folios", "digital", "running", 4),
    Case("Body text in several font families and styles", "digital", "fonts"),
    Case("External and internal hyperlinks", "digital", "links", 2),
    Case("Research notes with superscript and footnote text", "technical", "footnotes"),
    Case("Typeset equations and mathematical symbols", "technical", "math"),
    Case("Monospaced code sample and indentation", "technical", "code"),
    Case("Clean image-only English certificate", "scans", "clean-scan"),
    Case("English page rasterized at 80 DPI", "scans", "low-scan"),
    Case("English scan rotated by 90 degrees", "scans", "rotate-scan"),
    Case("Urdu digital text in right-to-left script", "rtl", "rtl", languages=("urd",)),
    Case("Arabic digital text in right-to-left script", "rtl", "rtl", languages=("ara",)),
    Case("English, Urdu, and Arabic on one digital page", "multilingual", "mixed-script", languages=("eng", "urd", "ara")),
    Case("Digital cover followed by a scanned page", "scans", "mixed-scan", 2),
    Case("Landscape-format meeting brief", "complex-layout", "landscape"),
    Case("Portrait, landscape, and square pages in one document", "complex-layout", "varying", 3),
    Case("AES-encrypted fixture without a supplied password", "invalid", "protected", rejection="password-protected"),
    Case("Truncated PDF with a corrupt trailer", "invalid", "corrupt", rejection="corrupted"),
    Case("112-page digital reference manual", "large", "large", 112),
    Case("Interactive form with text and checkbox widgets", "forms", "form"),
    Case("Page with highlight and note annotations", "forms", "annotation"),
    Case("PDF with a cryptographic test signature", "forms", "signed"),
    Case("Mixed columns, grid table, and embedded artwork", "complex-layout", "composite"),
    Case("Long single-column incident summary", "digital", "paragraphs", 2),
    Case("Indented list with bullets and multilevel numbering", "digital", "lists"),
    Case("Public notice with centered headings and fine print", "digital", "poster"),
    Case("Blank separator between two written pages", "digital", "blank", 3),
    Case("Wide landscape spreadsheet-style matrix", "tables", "wide-grid"),
    Case("Borderless table using aligned text cells", "tables", "borderless"),
    Case("Multipage assessment rubric with repeated columns", "tables", "rubric", 5),
    Case("Color-filled table with highlighted total", "tables", "finance"),
    Case("Three-column editorial with staggered entries", "complex-layout", "three-columns"),
    Case("Sidebar, body area, and lower information block", "complex-layout", "sidebar"),
    Case("Small custom landscape label", "complex-layout", "small"),
    Case("Portrait sheet with page rotation metadata", "complex-layout", "page-rotation"),
    Case("Narrow mobile-format document", "complex-layout", "narrow"),
    Case("Content shaped by varied page margins", "complex-layout", "insets", 3),
    Case("Source drawing with geometric markup", "images", "diagram"),
    Case("Transparent PNG over a colored rectangle", "images", "alpha"),
    Case("Two original raster landscapes with captions", "images", "gallery"),
    Case("Grayscale photograph in a print proof", "images", "gray-art"),
    Case("Diagram legend with raster swatches and vector notes", "images", "legend"),
    Case("Small compressed logo alongside digital prose", "images", "logo"),
    Case("English page skewed by 3.5 degrees", "scans", "skew-scan"),
    Case("English scan with seeded Gaussian sensor noise", "scans", "noisy-scan"),
    Case("Faded low-contrast English scan", "scans", "faded-scan"),
    Case("English page scanned upside down", "scans", "inverted-scan"),
    Case("Scanned invoice with a ruled table", "scans", "table-scan"),
    Case("Two English pages scanned at different resolutions", "scans", "mixed-dpi", 2),
    Case("Sparse text on an otherwise empty scanned form", "scans", "sparse-scan"),
    Case("Digital reference number over an English scanned page", "scans", "mixed-layer"),
    Case("Clean image-only Urdu letter", "rtl", "rtl-scan", languages=("urd",)),
    Case("Clean image-only Arabic notice", "rtl", "rtl-scan", languages=("ara",)),
    Case("Urdu scan with mild skew", "rtl", "rtl-skew", languages=("urd",)),
    Case("Noisy Arabic notice scan", "rtl", "rtl-noise", languages=("ara",)),
    Case("English and Urdu sections in the same scan", "multilingual", "mixed-script-scan", languages=("eng", "urd")),
    Case("English and Arabic sections in the same scan", "multilingual", "mixed-script-scan", languages=("eng", "ara")),
    Case("French accents and English terminology", "multilingual", "latin-script", languages=("eng", "fra")),
    Case("Spanish and German words with diacritics", "multilingual", "latin-script", languages=("spa", "deu")),
    Case("English and Japanese digital labels", "multilingual", "cjk", languages=("eng", "jpn")),
    Case("Arabic and Urdu paragraphs with Latin docket identifiers", "rtl", "mixed-script", languages=("ara", "urd", "eng")),
    Case("Separate English and Arabic pages with mixed scan status", "multilingual", "mixed-language-pages", 2, ("eng", "ara")),
    Case("Digital Spanish page followed by a low-resolution English scan", "multilingual", "mixed-language-pages", 2, ("spa", "eng")),
    Case("Technical specification with unit symbols and subscripts", "technical", "math"),
    Case("Installation note with a small inline command listing", "technical", "code", 2),
    Case("Keyboard shortcuts and literal punctuation", "technical", "shortcuts"),
    Case("Article with repeated superscript references", "technical", "footnotes", 2),
    Case("Engineering schematic and dimension labels", "technical", "diagram"),
    Case("Change log with fenced-looking monospaced blocks", "technical", "code"),
    Case("API lookup table with dotted and underscored identifiers", "technical", "technical-grid"),
    Case("Lined laboratory worksheet with empty input boxes", "forms", "form"),
    Case("Checkbox checklist with checked and unchecked values", "forms", "checkboxes"),
    Case("Review sheet with multiple annotation types", "forms", "annotation"),
    Case("Document with PDF bookmarks and linked destinations", "digital", "links", 4),
    Case("Typography stress case with varying sizes and weights", "digital", "fonts"),
    Case("Appendix with recurring page furniture and one blank page", "digital", "running-blank", 5),
    Case("Thirty-two-page medium-length technical report", "large", "handbook", 32),
    Case("128-page digital document with recurring page numbers", "large", "large-running", 128),
    Case("144-page digital document containing periodic tables", "large", "large-table", 144),
    Case("Forty-page image-bearing illustrated catalogue", "large", "large-images", 40),
    Case("Landscape signatures and multi-column conclusion", "complex-layout", "composite", 2),
    Case("Nested indentation and boundary-aligned headings", "complex-layout", "sidebar", 2),
    Case("Merged header spanning columns in a grid", "tables", "merged"),
    Case("Cell text on two wrapped lines", "tables", "wrapped"),
    Case("Inspection matrix with blank cells", "tables", "empty-cells"),
    Case("Unequal column widths and numerical values", "tables", "complex-grid"),
    Case("Two tables separated by a caption", "tables", "double-grid"),
    Case("Four-page report with charts and raster artwork", "images", "chart-gallery", 4),
    Case("Plain text presented with a PDF filename", "invalid", "bad-signature", rejection="valid PDF signature"),
    Case("PDF structure with a damaged cross-reference table", "invalid", "bad-xref", rejection="structure is damaged"),
    Case("Structurally valid PDF exceeding the default 500-page limit", "invalid", "page-limit", 501, rejection="page processing limit"),
    Case("PDF page with unsupported dimensions", "invalid", "dimension-limit", rejection="exceeds the supported page size"),
    Case("PDF catalog without document pages", "invalid", "empty-pdf", rejection="does not contain any pages"),
)

DATASET_VERSION = "synthetic-v1.0.0"
SCAN_DESIGNS = {
    "clean-scan", "low-scan", "rotate-scan", "mixed-scan", "skew-scan", "noisy-scan", "faded-scan",
    "inverted-scan", "table-scan", "mixed-dpi", "sparse-scan", "mixed-layer", "rtl-scan", "rtl-skew",
    "rtl-noise", "mixed-script-scan", "mixed-language-pages",
}


def entries() -> dict[str, Case]:
    return {f"PDF-{number:03}": case for number, case in enumerate(CASES, start=1)}
