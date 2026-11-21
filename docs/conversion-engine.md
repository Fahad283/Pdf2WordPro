# Conversion engine

The worker calls a replaceable engine through the `convert_pdf` entry point in `app.engines`. Native, scanned, and visual conversion strategies share the same options, progress callback, result metrics, and output validation. The toolkit dispatches other PDF operations through `run_tool`.

## Input to DOCX

1. Check the PDF signature, structural readability, encryption, page count, and geometry. Parse page selections before processing.
2. Inspect geometry, rotation, extractable text, drawing paths, image coverage, annotations, and links. Distinguish pages with reliable text from pages that require OCR.
3. Run Tesseract on pages requiring recognition and score recognized words. With automatic OCR, keep reliable native text in digital regions of mixed pages. OCRmyPDF handles the separate searchable-PDF tool and preserves the PDF format.
4. Group spans and lines by position, spacing, and font characteristics. Estimate margins, headings, reading order, columns, tables, images, and repeated running text.
5. Rebuild paragraphs, tables, lists, and headings with Word objects. Carry supported text style and link data into runs. Include section geometry, headers and footers, and native right-to-left properties when available.
6. Reopen the output and verify the ZIP and XML package. When render validation is enabled and LibreOffice is installed, render the DOCX to PDF and compare page count, text retention, and raster similarity. Return warnings when results diverge.

## Mode behavior

| Mode | Output |
| --- | --- |
| Editable layout | Native Word content with source page proportions, positioning, and formatting estimated from the PDF. |
| Flowing text | Native Word content in reading order. Word can reflow it when text or page settings change. |
| Visual layout | A rasterized source page per Word page. Page content is selectable as a picture. |

## Limits

PDF stores painting instructions. Section boundaries, table structure, logical reading order, and heading semantics often have to be inferred. Irregular columns, layered figures, borderless tables, rotated text, unsupported fonts, and atypical encodings can produce reordered or missing content. Some vector content and background fills may be simplified in editable modes. Visual mode is best when exact placement matters more than selecting text. The Word rendering engine, installed fonts, and page reflow can produce layout differences even when the DOCX opens cleanly.

Scanned text accuracy depends on resolution, contrast, language selection, skew, and layout. Handwriting, decorative lettering, and very small characters are especially difficult. Right-to-left paragraphs are supported where detected. Mixed-script positioning and table recognition remain heuristic. Links, document structure, and visually represented forms may survive in limited form. Embedded attachments, signatures, and PDF form interactivity are outside Word conversion. Modifying a signed PDF can invalidate its signature.

Editable column groups use borderless Word table cells. Scanned grids can become native tables when the engine detects consistent row and column rules and OCR recovers enough entries. Word uses installed fonts for source font names and may substitute families.

Render comparisons are diagnostic. Similarity changes with crop, pagination, font substitution, and page geometry. Reported peak memory is the worker process high-water mark and can include earlier jobs on the same process. Use the warnings and the editable result to review important documents.
