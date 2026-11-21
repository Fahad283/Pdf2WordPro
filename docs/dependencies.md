# Major dependency licenses

Python package pins are in `backend/requirements*.txt`. The frontend pins JavaScript dependencies in `frontend/package.json` and records the transitive graph in `frontend/package-lock.json`. Compose pins major or feature image tags so images can receive patch updates.

| Component | Upstream licensing |
| --- | --- |
| Next.js, React, Tailwind CSS, shadcn/ui, React Hook Form, Zod | MIT. |
| TypeScript | Apache License 2.0. |
| Lucide | ISC, with upstream notices for inherited icons. |
| FastAPI, Pydantic, SQLAlchemy, Alembic, Celery | MIT for FastAPI, Pydantic, SQLAlchemy and Alembic. Celery uses BSD 3-Clause. |
| PostgreSQL, Redis 8, psycopg | PostgreSQL License, AGPLv3 option for Redis 8, LGPLv3 for psycopg. |
| PyMuPDF and MuPDF | AGPLv3 or an Artifex commercial license. |
| Ghostscript | AGPLv3 or an Artifex commercial license. |
| python-docx, qpdf | MIT for python-docx. Apache License 2.0 for qpdf. |
| Tesseract and upstream language data | Apache License 2.0. |
| OCRmyPDF | MPL 2.0, with separately licensed dependencies. |
| Pillow, NumPy, OpenCV | HPND for Pillow, BSD 3-Clause for NumPy, Apache License 2.0 for OpenCV. |
| LibreOffice | MPL 2.0 and accompanying notices for included libraries. |
| ClamAV, Nginx, SeaweedFS, boto3 | GPLv2 for ClamAV, BSD 2-Clause for Nginx, Apache License 2.0 for SeaweedFS and boto3. |
| Argon2 and cryptography | MIT for argon2-cffi. Apache License 2.0 or BSD 3-Clause for cryptography. |

Review the exact upstream notices and distribution obligations before distributing images or launching a hosted product. In particular, PyMuPDF and Ghostscript have network-copyleft licensing considerations. The conversion engine interface lets a deployment replace components. [PyMuPDF licensing](https://pymupdf.readthedocs.io/en/latest/about.html) · [Ghostscript licensing](https://www.ghostscript.com/licensing/index.html) · [Redis licensing](https://redis.io/legal/licenses/).

SeaweedFS is the included S3-compatible option. The MinIO community repository is archived. The application uses S3 operations that are available on existing compatible servers. [SeaweedFS](https://github.com/seaweedfs/seaweedfs) · [MinIO repository](https://github.com/minio/minio).
