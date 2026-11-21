"""Public interfaces for PDF inspection and Word conversion."""

from .conversion import (
    BaseConversionEngine,
    NativePDFConversionEngine,
    ScannedPDFConversionEngine,
    VisualPDFConversionEngine,
    convert_pdf,
)
from .pdf_source import EngineError, inspect_pdf, open_pdf, select_pages

__all__ = [
    "BaseConversionEngine",
    "EngineError",
    "NativePDFConversionEngine",
    "ScannedPDFConversionEngine",
    "VisualPDFConversionEngine",
    "convert_pdf",
    "inspect_pdf",
    "open_pdf",
    "select_pages",
]
