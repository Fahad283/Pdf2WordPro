# Pdf2WordPro
<div align="center">

# 📄 PDF to Word Pro & PDF2DOCX-BENCH v1.0

**Self-hosted, privacy-first PDF to Word conversion engine, 14-tool document utility suite, and automated quality assurance benchmarking platform.**

[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](#quick-start-with-docker)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](#development--testing)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-black?style=for-the-badge&logo=next.js&logoColor=white)](#development--testing)
[![OCR Powered](https://img.shields.io/badge/OCR-Tesseract%20%7C%20OCRmyPDF-success?style=for-the-badge)](#conversion-modes)
[![Benchmarking](https://img.shields.io/badge/QA%20Platform-PDF2DOCX--BENCH-blueviolet?style=for-the-badge)](#-pdf2docx-bench-qa-platform)
[![Self-Hosted](https://img.shields.io/badge/Privacy-100%25%20Self--Hosted-black?style=for-the-badge)](#security--administration)

[Quick Start](#-quick-start-with-docker) • [Conversion Modes](#-conversion-modes) • [Benchmarking Platform](#-pdf2docx-bench-qa-platform) • [Architecture & Guides](#-documentation--guides) • [Testing](#-development--testing)

</div>

---

**PDF to Word Pro** converts digital and scanned PDFs into fully editable Microsoft Word (`.docx`) documents—running entirely locally or on your own server. Alongside high-accuracy conversion, it executes OCR and **13 additional PDF utilities** through a unified upload, asynchronous background job, and batch download workflow.

It also integrates **PDF2DOCX-BENCH v1.0**, an automated, production-grade benchmarking and quality assurance platform providing automated document quality scoring, visual layout computer vision comparison, OCR accuracy metrics, ECMA-376 DOCX validation, and commercial reference comparison (e.g. against iLovePDF).

---

## ✨ Key Highlights

* **🔒 100% Self-Hosted & Private:** Your documents never leave your infrastructure. Built-in auto-expiration purges files after 60 minutes by default.
* **🌍 Multi-Language OCR Out of the Box:** Pre-configured worker containers include **English, Urdu, and Arabic** language packs, automatic orientation detection, `OCRmyPDF`, and `LibreOffice`.
* **⚡ Batch Processing & Async Queue:** Upload multiple files simultaneously, monitor individual job progress and warnings in real time, and export completed batches as a single `.zip` archive.
* **🛡️ Production-Ready Security:** Supports anonymous uploads out of the box, role-based admin dashboards, optional fail-closed **ClamAV** malware scanning, and S3-compatible object storage.
* **🧰 Complete PDF Toolkit:** Includes PDF-to-Word conversion plus 13 integrated PDF utilities powered by the same background worker pipeline.
* **📊 PDF2DOCX-BENCH QA Platform:** Comprehensive 100-case synthetic test dataset, 100-point weighted scoring model, character/word error rate (CER/WER) analysis, visual layout diffs, and multi-format reporting (JSON, CSV, HTML, PDF).

---

## 🎯 Conversion Modes

When converting documents, choose the engine mode that best fits your layout requirements:

| Mode | Best For | Behavior |
| :--- | :--- | :--- |
| **Standard (Default)** | General documents, forms & reports | Reconstructs editable paragraphs, tables, and embedded images. |
| **Flowing Text** | Articles, books & heavy text edits | Prioritizes continuous reading order for seamless editing in Word. |
| **Visual Layout** | Complex graphics & fixed designs | Embeds a high-resolution rendered image of each page to preserve exact visual fidelity. |

> **Smart OCR:** Scanned pages are detected and processed via OCR automatically unless disabled. Simply select the expected document languages before starting the job.

---

## 📊 PDF2DOCX-BENCH QA Platform

PDF to Word Pro includes an embedded benchmarking subsystem accessible at `/benchmark` for administrators:

* **100-Point Weighted Scoring Engine**: Text accuracy (20 pts), Layout preservation (20 pts), Tables and formatting (15 pts), Images and graphics (10 pts), OCR performance (10 pts), DOCX compatibility (10 pts), Performance (5 pts), Reliability (4 pts), Security (4 pts), and Language support (2 pts).
* **Synthetic Test Dataset**: 100 pre-designed test cases spanning digital layouts, tables, scanned documents, Urdu/Arabic RTL text, technical charts, forms, and security stress tests with ground-truth manifests.
* **Visual & Layout Computer Vision**: Headless LibreOffice DOCX-to-PDF rendering, page-by-page SSIM visual similarity, bounding-box IoU alignment, and difference overlay maps.
* **Structural DOCX Validation**: ECMA-376 / ISO/IEC 29500 package inspection, XML relationship checks, font/style validation, and editable text verification.
* **Commercial Reference Testing**: Side-by-side comparison between the original PDF, internal conversion output, and commercial reference engines (such as iLovePDF).
* **Exportable Reports**: One-click exports of benchmark runs in JSON, CSV, interactive standalone HTML, and executive PDF formats.

---

## 🚀 Quick Start with Docker

### Prerequisites
* **macOS / Windows:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (with Docker Compose; Windows uses Linux containers).
* **Linux:** Docker Engine and the Docker Compose plugin.

### 1. Configure Environment Secrets

Clone the repository, navigate to the project root, and generate secure credentials for PostgreSQL and application signing:

<details open>
<summary><b>🐧 macOS & Linux</b></summary>

```bash
test -f .env || cp .env.example .env
openssl rand -hex 24   # Use for POSTGRES_PASSWORD
openssl rand -hex 32   # Use for SECRET_KEY
```
</details>

<details>
<summary><b>🪟 Windows (PowerShell)</b></summary>

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
</details>

Set `POSTGRES_PASSWORD` and `SECRET_KEY` in `.env`. To create an administrator account on initial startup, set:
```ini
ADMIN_EMAIL=admin@yourdomain.com
ADMIN_PASSWORD=YourSecurePassword123!
```

### 2. Build and Start the Stack

```bash
docker compose up --build -d --wait
docker compose ps
```

### 3. Access the Application

* **Web UI & Tools**: [http://localhost:3000](http://localhost:3000)
* **Benchmark Platform**: [http://localhost:3000/benchmark](http://localhost:3000/benchmark) (Admin login required)
* **API Documentation**: [http://localhost:3000/api/v1/docs](http://localhost:3000/api/v1/docs)
* **Health Check**: [http://localhost:3000/api/v1/health](http://localhost:3000/api/v1/health)

---

## 🛠️ Production Overlays

The stack includes modular Compose overlays for production deployments:

* **Fail-Closed Antivirus Scanning (ClamAV)**:
  ```bash
  docker compose -f docker-compose.yml -f compose.scanning.yml up --build -d --wait
  ```
* **S3-Compatible Storage (SeaweedFS or AWS S3)**:
  ```bash
  docker compose -f docker-compose.yml -f compose.s3.yml up --build -d --wait
  ```
* **Full Production HTTPS with Nginx**:
  ```bash
  docker compose -f docker-compose.yml -f compose.scanning.yml -f compose.production.yml up --build -d --wait
  ```

---

## 🧪 Development & Testing

### Backend & Benchmark Engine Tests
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt -r requirements-ocr.txt
alembic upgrade head
pytest -q
```

### Frontend Typecheck & Build
```bash
cd frontend
npm ci
npm run typecheck
npm run build
```

---

## 📚 Documentation & Guides

- [System Architecture](docs/architecture.md)
- [Benchmark Platform Architecture](docs/benchmark-architecture.md)
- [REST API Specification](docs/api.md)
- [Conversion Engine & Layout Pipeline](docs/conversion-engine.md)
- [Production Deployment Guide](docs/deployment.md)
- [Security, Malware & Retention Policies](docs/security.md)
- [Quality Testing & Verification](docs/testing.md)
- [Dependency Licenses](docs/dependencies.md)

---

## 📄 License

This project is licensed under the terms of the repository license. See [docs/dependencies.md](docs/dependencies.md) for third-party component licenses.
