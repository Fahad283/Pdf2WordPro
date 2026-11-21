# Deployment

The default Compose stack publishes Next.js on loopback port 3000. FastAPI, PostgreSQL, Redis, and the Celery worker stay on an internal Docker network. Alembic runs as a one-shot service before the application starts. The platform uses a private local volume by default.

```bash
docker compose up --build -d --wait
docker compose logs --tail 80 api worker beat
docker compose stop
```

## Malware scanning

Enable the scanning overlay for a ClamAV service with a persistent signature volume. The application waits for the daemon and rejects uploads when the required scanner is unavailable.

```bash
docker compose -f docker-compose.yml -f compose.scanning.yml up --build -d --wait
```

Allow up to 4 GB for ClamAV during signature reloads. If the Docker VM has a small memory allocation, raise it before enabling the scanning overlay. If the deployment operates a separate ClamAV daemon, set `CLAMAV_HOST`, `CLAMAV_PORT`, and `CLAMAV_REQUIRED=true` and provide a private route to it.

## S3-compatible storage

Set unique `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY` in `.env` and add the S3 overlay. It starts SeaweedFS on the private network and creates the configured bucket at startup.

```bash
docker compose -f docker-compose.yml -f compose.s3.yml up --build -d --wait
```

The S3 adapter also works against a compatible private bucket you maintain, such as AWS S3 or an existing MinIO deployment. Set `STORAGE_BACKEND=s3`, `S3_BUCKET`, and the region, endpoint, and credentials appropriate to the provider. For managed S3, give the API, worker, and cleanup worker network access to the endpoint through a private endpoint or controlled egress. Provision least-privilege permissions for bucket health checks and object read, write, and delete operations. Moving an existing deployment between storage drivers requires migrating or expiring its existing objects first.

## HTTPS deployment

1. Point the deployment hostname at the host. Set `SITE_URL` and `CORS_ORIGINS` to the corresponding `https://` origin.
2. Set `TLS_DIR` to the directory with `fullchain.pem` and `privkey.pem`. Renew certificates using the hosting environment's preferred mechanism and reload Nginx afterward.
3. Generate independent high-entropy values for `SECRET_KEY` and `POSTGRES_PASSWORD` and provision an administrator.
4. Start the HTTPS stack.

```bash
docker compose -f docker-compose.yml -f compose.scanning.yml -f compose.production.yml up --build -d --wait
```

The production overlay enables secure cookies, requires PostgreSQL and a scanner, and exposes only Nginx. Nginx forwards streams without response buffering. Only apply the trusted proxy settings to deployments where the configured edge controls traffic into the frontend.

Each worker defaults to one processing slot, a 2 CPU ceiling, a 3 GB memory ceiling, and an isolated temporary filesystem. Provision more workers for throughput and map them to the same database, Redis, and storage. Run a single Beat instance. For multi-host or horizontal API deployment use shared storage. Monitor Redis memory, worker backlog, failed jobs, database capacity, and scanner health.

## Environment variables

| Setting | Default and purpose |
| --- | --- |
| `POSTGRES_PASSWORD` | Required by Compose. Use URL-safe characters because Compose includes it in the SQLAlchemy URL. |
| `SECRET_KEY` | Required by Compose. Signs session credentials and protects transient job secrets. Rotating it invalidates sessions and pending protected-file jobs. |
| `ENVIRONMENT` | `development` in Compose. The HTTPS overlay selects `production`. |
| `SITE_URL` | `http://localhost:3000`. Public origin used for metadata and built into the frontend image. |
| `FRONTEND_BIND`, `FRONTEND_PORT` | `127.0.0.1` and `3000` for the local published port. |
| `CORS_ORIGINS`, `COOKIE_SECURE` | Allowed browser origins and secure session cookie setting. |
| `DATABASE_URL`, `REDIS_URL` | Container URLs supplied by Compose. Native development can provide these directly to the API and worker. |
| `STORAGE_DIR`, `WORK_DIR` | Private objects directory and isolated temp parent. Compose mounts both. |
| `MAX_UPLOAD_MB`, `MAX_OUTPUT_MB`, `MAX_PAGES`, `MAX_BATCH_FILES` | Default limits of 50 MB input, 256 MB output, 500 pages, and 10 batch files. |
| `RETENTION_MINUTES`, `METADATA_RETENTION_DAYS` | Default 60 minutes for binaries and 30 days for operational metadata. |
| `DAILY_CONVERSION_LIMIT`, `JOB_TIMEOUT_SECONDS` | Default 40 jobs per account or guest session per day and a 300-second worker limit. |
| `OCR_LANGUAGES` | Comma-separated allowlist, default `eng,urd,ara`. Install corresponding Tesseract language packages in the worker image before adding codes. |
| `WORKER_CONCURRENCY` | `1`. Size worker resources before increasing parallelism. |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Optional initial administrator credentials. |
| `STORAGE_BACKEND`, `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Select private local storage or an S3-compatible endpoint. |
| `CLAMAV_HOST`, `CLAMAV_PORT`, `CLAMAV_REQUIRED` | Optional local scanner connection. The scan overlay sets `clamav:3310` and requires it. |
| `TLS_DIR` | Certificate directory used by the HTTPS overlay. |
| `CELERY_TASK_ALWAYS_EAGER` | In-process task execution for native testing. The Compose stack uses Celery and Redis. |

## Native development

Run the backing services or use a development SQLite database and a local Redis daemon. Run Alembic before starting FastAPI, and launch the worker and scheduler from the same backend directory with the same settings.

```bash
cd backend
python -m pip install -r requirements-dev.txt -r requirements-ocr.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In two other terminals in `backend`:

```bash
celery -A app.workers.celery_app:celery_app worker --loglevel=INFO --concurrency=1
celery -A app.workers.celery_app:celery_app beat --loglevel=INFO
```

In `frontend`, run `npm ci` and `npm run dev`. The frontend defaults to proxying `http://127.0.0.1:8000`. Set `API_INTERNAL_URL` before startup to change the upstream. Install Tesseract, its language packs, qpdf, LibreOffice, and OCRmyPDF's system dependencies for native document processing. Docker has a consistent toolchain across the supported operating systems.

`docker compose stop` preserves storage and job data. `docker compose down` removes the stack containers and networks. Passing `-v` also removes the stack's volumes and their data.
