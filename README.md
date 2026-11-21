# PDF to Word Pro

PDF to Word Pro converts digital and scanned PDFs into editable Word documents. It also runs OCR and 13 other PDF utilities through the same upload, background job, and download workflow. The conversion engine and document tools run locally or on your server.

## Run with Docker

Install Docker Desktop with Compose on macOS or Windows. On Linux, install Docker Engine and the Compose plugin. Start Docker and open a terminal in the repository.

On macOS and Linux:

```bash
test -f .env || cp .env.example .env
openssl rand -hex 24
openssl rand -hex 32
```

For a new setup, set `POSTGRES_PASSWORD` in `.env` to the first value and `SECRET_KEY` to the second. Keep existing credentials when restarting a stack. On Windows PowerShell, copy the file and generate two values with the following commands. Docker Desktop uses Linux containers.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
$random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
1..2 | ForEach-Object {
    $bytes = New-Object byte[] 32
    $random.GetBytes($bytes)
    ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
}
$random.Dispose()
```

Then build and start the default stack:

```bash
docker compose up --build -d --wait
docker compose ps
```

Open [PDF to Word Pro](http://localhost:3000). [API documentation](http://localhost:3000/api/v1/docs) and the [health endpoint](http://localhost:3000/api/v1/health) are served on the same origin. The worker image includes English, Urdu, Arabic, orientation data, OCRmyPDF, and LibreOffice. The first image build downloads those language packs and system packages.

Anonymous uploads work immediately. To enable an administrator, set `ADMIN_EMAIL` and a strong `ADMIN_PASSWORD` before starting the API. Sign in normally and open `/admin`. Clear the bootstrap values after the account is created and recreate the API container.

Add `compose.scanning.yml` for fail-closed ClamAV scanning, `compose.s3.yml` for the optional local S3-compatible store, and the production overlay for HTTPS. See [Deployment](docs/deployment.md) for the commands, environment variables, and sizing guidance.

## Convert a document

Open **PDF to Word**, add one or more PDFs, and choose a conversion mode. The default reconstructs editable paragraphs, tables, and images. **Flowing text** prioritizes continuous reading order and **Visual layout** embeds a rendered image of each page. Scanned pages use OCR automatically unless you change the setting. Select the languages you expect to appear in the document.

Each file has its own progress, warnings, and download. A batch can be downloaded as a ZIP after its jobs finish. Results and original uploads expire after 60 minutes by default. Their expiration times are available in the API.

## Test

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Use `.venv\Scripts\Activate.ps1` on Windows PowerShell. Engine tests that use Tesseract, OCRmyPDF, or LibreOffice detect those binaries. For the complete engine test suite, use the worker image as described in [Testing](docs/testing.md).

```bash
cd frontend
npm ci
npm run typecheck
npm run build
```

## Project guides

- [Architecture](docs/architecture.md)
- [API](docs/api.md)
- [Conversion engine](docs/conversion-engine.md)
- [Deployment](docs/deployment.md)
- [Security and retention](docs/security.md)
- [Testing and quality measurement](docs/testing.md)
- [Dependency licenses](docs/dependencies.md)
