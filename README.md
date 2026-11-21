# Pdf2WordPro
<div align="center">

# 📄 PDF to Word Pro

**Self-hosted, privacy-first PDF to Word conversion engine and document utility suite.**

[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](#quick-start-with-docker)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](#development--testing)
[![OCR Powered](https://img.shields.io/badge/OCR-Tesseract%20%7C%20OCRmyPDF-success?style=for-the-badge)](#conversion-modes)
[![Self-Hosted](https://img.shields.io/badge/Privacy-100%25%20Self--Hosted-black?style=for-the-badge)](#security--administration)

[Quick Start](#quick-start-with-docker) • [Conversion Modes](#conversion-modes) • [Architecture & Guides](#documentation) • [Testing](#development--testing)

</div>

---

**PDF to Word Pro** converts digital and scanned PDFs into fully editable Microsoft Word (`.docx`) documents—running entirely locally or on your own server. Alongside high-accuracy conversion, it executes OCR and **13 additional PDF utilities** through a unified upload, asynchronous background job, and batch download workflow.

## ✨ Key Highlights

* **🔒 100% Self-Hosted & Private:** Your documents never leave your infrastructure. Built-in auto-expiration purges files after 60 minutes by default.
* **🌍 Multi-Language OCR Out of the Box:** Pre-configured worker containers include **English, Urdu, and Arabic** language packs, automatic orientation detection, `OCRmyPDF`, and `LibreOffice`.
* **⚡ Batch Processing & Async Queue:** Upload multiple files simultaneously, monitor individual job progress and warnings in real time, and export completed batches as a single `.zip` archive.
* **🛡️ Production-Ready Security:** Supports anonymous uploads out of the box, role-based admin dashboards, optional fail-closed **ClamAV** malware scanning, and S3-compatible object storage.
* **🧰 Complete PDF Toolkit:** Includes PDF-to-Word conversion plus 13 integrated PDF utilities powered by the same background worker pipeline.

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
openssl rand -hex 24
openssl rand -hex 32<div align="center">

# 📄 PDF to Word Pro

**Self-hosted, privacy-first PDF to Word conversion engine and document utility suite.**

[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](#quick-start-with-docker)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](#development--testing)
[![OCR Powered](https://img.shields.io/badge/OCR-Tesseract%20%7C%20OCRmyPDF-success?style=for-the-badge)](#conversion-modes)
[![Self-Hosted](https://img.shields.io/badge/Privacy-100%25%20Self--Hosted-black?style=for-the-badge)](#security--administration)

[Quick Start](#quick-start-with-docker) • [Conversion Modes](#conversion-modes) • [Architecture & Guides](#documentation) • [Testing](#development--testing)

</div>

---

**PDF to Word Pro** converts digital and scanned PDFs into fully editable Microsoft Word (`.docx`) documents—running entirely locally or on your own server. Alongside high-accuracy conversion, it executes OCR and **13 additional PDF utilities** through a unified upload, asynchronous background job, and batch download workflow.

## ✨ Key Highlights

* **🔒 100% Self-Hosted & Private:** Your documents never leave your infrastructure. Built-in auto-expiration purges files after 60 minutes by default.
* **🌍 Multi-Language OCR Out of the Box:** Pre-configured worker containers include **English, Urdu, and Arabic** language packs, automatic orientation detection, `OCRmyPDF`, and `LibreOffice`.
* **⚡ Batch Processing & Async Queue:** Upload multiple files simultaneously, monitor individual job progress and warnings in real time, and export completed batches as a single `.zip` archive.
* **🛡️ Production-Ready Security:** Supports anonymous uploads out of the box, role-based admin dashboards, optional fail-closed **ClamAV** malware scanning, and S3-compatible object storage.
* **🧰 Complete PDF Toolkit:** Includes PDF-to-Word conversion plus 13 integrated PDF utilities powered by the same background worker pipeline.

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
openssl rand -hex 24
openssl rand -hex 32<div align="center">

# 📄 PDF to Word Pro

**Self-hosted, privacy-first PDF to Word conversion engine and document utility suite.**

[![Docker Ready](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](#quick-start-with-docker)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](#development--testing)
[![OCR Powered](https://img.shields.io/badge/OCR-Tesseract%20%7C%20OCRmyPDF-success?style=for-the-badge)](#conversion-modes)
[![Self-Hosted](https://img.shields.io/badge/Privacy-100%25%20Self--Hosted-black?style=for-the-badge)](#security--administration)

[Quick Start](#quick-start-with-docker) • [Conversion Modes](#conversion-modes) • [Architecture & Guides](#documentation) • [Testing](#development--testing)

</div>

---

**PDF to Word Pro** converts digital and scanned PDFs into fully editable Microsoft Word (`.docx`) documents—running entirely locally or on your own server. Alongside high-accuracy conversion, it executes OCR and **13 additional PDF utilities** through a unified upload, asynchronous background job, and batch download workflow.

## ✨ Key Highlights

* **🔒 100% Self-Hosted & Private:** Your documents never leave your infrastructure. Built-in auto-expiration purges files after 60 minutes by default.
* **🌍 Multi-Language OCR Out of the Box:** Pre-configured worker containers include **English, Urdu, and Arabic** language packs, automatic orientation detection, `OCRmyPDF`, and `LibreOffice`.
* **⚡ Batch Processing & Async Queue:** Upload multiple files simultaneously, monitor individual job progress and warnings in real time, and export completed batches as a single `.zip` archive.
* **🛡️ Production-Ready Security:** Supports anonymous uploads out of the box, role-based admin dashboards, optional fail-closed **ClamAV** malware scanning, and S3-compatible object storage.
* **🧰 Complete PDF Toolkit:** Includes PDF-to-Word conversion plus 13 integrated PDF utilities powered by the same background worker pipeline.

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
openssl rand -hex 24
openssl rand -hex 32
