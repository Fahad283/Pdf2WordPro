# REST API

All routes below use the `/api/v1` prefix. The running application serves interactive API documentation at [Swagger UI](http://localhost:3000/api/v1/docs) and its schema at [OpenAPI](http://localhost:3000/api/v1/openapi.json).

The API sets an HttpOnly guest cookie on the first request that needs an identity. Use the same cookie for uploads, job status, events, and downloads. Account authentication also uses a cookie. Browser write requests must come from an allowed origin.

| Method and path | Behavior |
| --- | --- |
| `GET /health` | Reports database, Redis, storage, and scanner readiness. |
| `GET /config` | Returns current page, upload, batch and per-day limits, the retention window, and allowed OCR languages. |
| `POST /files/upload` | Upload one multipart `file`. Returns owner-scoped ID, sanitized name, byte size, page count when known, and expiry. |
| `DELETE /files/{file_id}` | Deletes an upload. Active jobs must be cancelled first. |
| `POST /pdf/inspect` | Inspect a previously uploaded PDF by `file_id`. |
| `POST /pdf/ocr` | Queue a searchable-PDF job by `file_id` with OCR options. |
| `POST /conversions` | Queue a tool job and return its initial status. |
| `POST /conversions/batch` | Queue independent jobs and return a batch ID and jobs. |
| `GET /conversions/{job_id}` | Get job status, progress, warnings, metrics, and output name. |
| `GET /conversions/{job_id}/events` | Server-sent `status` events carrying the same job JSON. |
| `GET /conversions/{job_id}/download` | Download a completed, unexpired result. |
| `GET /conversions/batches/{batch_id}/download` | Download the available batch results as ZIP. |
| `POST /conversions/{job_id}/retry` | Retry a failed or cancelled job while the originals remain available. Include a fresh password for password jobs. |
| `POST /conversions/{job_id}/cancel` | Cancel a queued or processing job. Processing checks for cancellation at progress boundaries. |
| `DELETE /conversions/{job_id}` | Remove access, stop a running job, and delete its output and inputs when they are no longer shared by another job. |
| `GET /conversions/history` | List recent owner-scoped jobs. |
| `POST /auth/register`, `POST /auth/login` | Send an email and password. Creates a session and associates current guest work with the account. |
| `POST /auth/logout`, `GET /auth/me` | End a session or retrieve the current user. |
| `GET /admin/metrics`, `GET /admin/users`, `PATCH /admin/users/{id}` | Read aggregate operational data and manage account status or plan. Requires an administrator. |
| `GET /admin/settings`, `PATCH /admin/settings` | Read and update upload, page, batch, conversion, OCR, and retention settings. Requires an administrator. |

## Submit a conversion

Upload using a cookie jar and take `id` from the JSON response.

```bash
curl -sS -b cookies.txt -c cookies.txt -F 'file=@sample.pdf' \
  http://localhost:3000/api/v1/files/upload
```

Send a job request with the uploaded file ID.

```json
{
  "tool": "pdf-to-word",
  "file_ids": ["00000000-0000-0000-0000-000000000000"],
  "settings": {
    "mode": "editable",
    "ocr": "auto",
    "languages": ["eng", "urd"],
    "pages": "1-3,5",
    "preserve_images": true,
    "preserve_tables": true
  }
}
```

Use a one-based page list with inclusive ranges. `mode` supports `editable`, `flowing`, and `visual`. `ocr` supports `auto`, `force`, and `off` for Word conversion. Options also include `preserve_columns`, `preserve_headers_footers`, `preserve_hyperlinks`, `preserve_page_size`, `preserve_page_breaks`, and `validate_render`. Omit settings to use the defaults.

A single job normally takes one file. Merge and JPG to PDF accept an ordered list and create one output. The batch endpoint queues a separate job for each file for independent-file tools.

| Tool ID | Output and additional settings |
| --- | --- |
| `pdf-to-word` | DOCX. |
| `word-to-pdf` | PDF from DOCX. |
| `merge-pdf` | PDF in source upload order. |
| `split-pdf` | ZIP of PDFs. With `split_mode:"ranges"`, each comma-separated range produces a part. |
| `compress-pdf` | PDF. `compression` is `lossless`, `balanced`, or `strong`. |
| `rotate-pdf` | PDF. `rotation` is 90, 180, or 270 degrees clockwise. |
| `extract-pages`, `delete-pages` | PDF using the supplied `pages`. |
| `pdf-to-jpg` | ZIP of JPEGs. `dpi` is 72 to 300. |
| `jpg-to-pdf` | PDF in source image order. |
| `ocr-pdf` | Searchable PDF. Accepts `languages`, `pages`, and `ocr` of `auto` or `force`. |
| `watermark-pdf` | PDF with the supplied text on selected pages. |
| `page-numbers` | PDF with numbers on selected pages, beginning at `start_number`. |
| `protect-pdf`, `unlock-pdf` | AES-256 protected PDF or decrypted PDF. Supply the document `password`. |

Read the job ID and use it to collect updates and download:

```bash
curl -sS -N -b cookies.txt http://localhost:3000/api/v1/conversions/JOB_ID/events
curl -fsS -b cookies.txt -o result.docx http://localhost:3000/api/v1/conversions/JOB_ID/download
```

Job states are `queued`, `processing`, `completed`, `failed`, and `cancelled`. HTTP errors return a readable `detail`. Common outcomes include 404 for a missing or inaccessible job, 409 when a job is in the wrong state for an operation, 410 for expired output, 413 for size limits, 422 for invalid documents or settings, and 429 for rate or quota limits.
