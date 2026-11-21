# Testing and quality measurements

Tests build original fixtures at runtime using PyMuPDF, Pillow, and python-docx. Synthetic fixtures exercise digital text, columns, tables, invoices, images, OCR, rotation, mixed PDFs, encryption, right-to-left text, unusual fonts, and damaged input. API tests exercise the upload and job lifecycle, account boundaries, invalid input, and expiry. The toolkit tests open each generated PDF or archive and inspect its contents.

## Local test commands

```bash
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

To run the engine tests inside the worker image with its system tools and language packs:

```bash
docker compose build worker
docker run --rm --tmpfs /tmp:rw,mode=1777 \
  -e DATABASE_URL=sqlite:////tmp/pdfpro-tests.sqlite3 -e ENVIRONMENT=test \
  pdf-word-pro-worker:local sh -c \
  'pip install --target /tmp/test-deps pytest==9.1.1 httpx==0.28.1 && PYTHONPATH=/tmp/test-deps:/srv/app python -m pytest -q -p no:cacheprovider'
```

On PowerShell, run the equivalent `docker run` command on a single line or use PowerShell's continuation character. The worker runs under a restricted account, so in-image test dependencies are installed in a temporary directory for this command.

## Live stack

With Docker Compose running and the Python dev dependencies installed, test the public frontend origin:

```bash
cd backend
PDF_PRO_LIVE_URL=http://localhost:3000 python -m pytest -q tests/test_live_stack.py
```

This exercises the Next.js proxy, FastAPI, PostgreSQL, Redis, and Celery together. It uploads generated text and scanned PDFs, observes events, opens the downloaded DOCX and ZIP packages, checks the three modes, and verifies owner isolation and deletion. It removes its test uploads and jobs after completion.

## Quality signals

Check the output for native Word paragraphs, rows, cells, images, and page sections. Compare known fixture text to extracted or OCR text in reading order, with character and word error rates computed from edit distance. Package checks look for missing images and invalid ZIP/XML entries. Rendering checks compare pages and text against the source and report scaled image similarity. Record processing time and estimated peak memory for representative source sets when tuning worker resources. Absolute quality across arbitrary documents depends on their characteristics.
