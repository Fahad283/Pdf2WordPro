# Security and data retention

Files and jobs belong to a guest session or signed-in account. Each operation checks ownership on the server. Status streams and attachment downloads use the same authorization. An administrator can see aggregate usage and recent failure details. The administrator API does not return document content or storage keys.

Uploads have size, file format, and page bounds. The service assigns internal names independently of user-supplied filenames. File parsers run with restricted container permissions, and workers use private temporary work directories. DOCX input is checked for unsafe ZIP entries, macros, embedded objects, and external relationships that could cause LibreOffice to fetch remote resources. PDF and image processing is constrained by page geometry, raster limits, worker timeouts, CPU, memory, and output size. Production requires a healthy ClamAV service before accepting uploads.

Account passwords are hashed with Argon2. Document passwords for queued jobs are encrypted with a key derived from the application secret. Their short-lived entries are consumed by the worker and excluded from stored job options and task arguments. PDF unlock gives qpdf the password through a temporary mode-0600 job file inside the isolated workspace. Error responses describe common processing failures without including stack traces. Cookie sessions use HttpOnly and SameSite attributes. Production additionally requires Secure cookies and a configured origin allowlist. The HTTPS overlay limits direct network access to the frontend and uses Nginx as the trusted edge.

## Retention

Original uploads expire from upload time. Conversion outputs expire from completion time. Both use the configured retention window, which defaults to 60 minutes. Downloads and new job submissions enforce expiry immediately. Celery Beat schedules cleanup of expired data, and the cleanup worker retries deletions when the storage provider is unavailable. Removing a job removes access and requests deletion of its output and any inputs no longer shared with other jobs. An upload can also be removed directly once no active job is using it. Temporary inputs and outputs are removed after normal completion or a handled failure. If a process stops during a storage write, the worker reclaims the abandoned object after a 55-minute grace period.

Metadata retained after file expiry includes filenames, size, job history, and operational errors for up to 30 days by default. Account records last until removed by the operator. Configure database backups, provider logs, and object lifecycle policies consistently with the documented retention period. If you enable S3 versioning, expire noncurrent versions separately, since ordinary object deletion creates a delete marker.

## Deployment responsibilities

Operate the application and its storage on trusted infrastructure. Provision TLS, rotate secrets, keep renderer and scanner packages current, and monitor the expiry worker. A conversion result can retain document content and links from the source. PDF passwords control opening the file and should be shared separately from the PDF. The service depends on storage and network controls available to the operator. Store volumes and database backups on encrypted infrastructure when required by your deployment.
