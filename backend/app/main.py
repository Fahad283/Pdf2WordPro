import logging
import re
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.formparsers import MultiPartException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api import admin, auth, conversions, files, pdf
from app.benchmark.api import router as benchmark_router
from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.core.logging import configure_logging
from app.core.rate_limit import throttle
from app.core.security import Identity, get_identity
from app.schemas import ConfigView
from app.services.health import checks, healthy
from app.services.settings import effective_config

settings = get_settings()
logger = logging.getLogger(__name__)
API_PREFIX = "/api/v1"
UPLOAD_PATH = f"{API_PREFIX}/files/upload"
BENCHMARK_UPLOAD = re.compile(r"/api/v1/benchmarks/datasets/[^/]+/cases(?:/[^/]+/reference)?/?\Z")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _upload_limit() -> int:
    with SessionLocal() as db:
        # Reserve space for multipart boundaries, part headers, and the field name.
        return effective_config(db).max_upload_mb * 1024 * 1024 + 64 * 1024


class RequestPolicy:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        method = scope["method"]
        path = scope["path"]
        limit = 65_536
        if method not in SAFE_METHODS:
            origin = headers.get("origin")
            fetch_site = headers.get("sec-fetch-site")
            if origin is None and (referer := headers.get("referer")):
                try:
                    address = urlsplit(referer)
                    origin = f"{address.scheme}://{address.netloc}" if address.netloc else "null"
                except ValueError:
                    origin = "null"
            if ((origin is not None and origin not in settings.allowed_origins)
                    or (origin is None and fetch_site in {"cross-site", "same-site"})):
                await JSONResponse({"detail": "This request origin is not allowed."}, status_code=403)(scope, receive, send)
                return
            benchmark_upload = BENCHMARK_UPLOAD.fullmatch(path) is not None
            if path.rstrip("/") == UPLOAD_PATH or benchmark_upload:
                try:
                    await run_in_threadpool(throttle, Request(scope), "upload-ip", 120)
                    limit = await run_in_threadpool(_upload_limit)
                    if benchmark_upload:
                        limit += 512 * 1024
                except HTTPException as exc:
                    await JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)(
                        scope, receive, send,
                    )
                    return
                except Exception:
                    await JSONResponse({"detail": "Upload service is temporarily unavailable."}, status_code=503)(
                        scope, receive, send,
                    )
                    return
            raw_length = headers.get("content-length", "")
            if raw_length.isdecimal() and (len(raw_length) > 16 or int(raw_length) > limit):
                await self._too_large(scope, receive, send)
                return

        received = 0
        too_large = False

        async def bounded_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if method not in SAFE_METHODS and message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    too_large = True
                    # Starlette's multipart parser closes open temporary uploads on this exception.
                    raise MultiPartException("Upload limit exceeded.")
            return message

        async def secure_send(message: Message) -> None:
            if too_large:
                return
            if message["type"] == "http.response.start":
                response_headers = message.setdefault("headers", [])
                response_headers.extend([
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                ])
                if not any(key == b"cache-control" for key, _ in response_headers):
                    response_headers.append((b"cache-control", b"no-store"))
            await send(message)

        try:
            await self.app(scope, bounded_receive, secure_send)
        except MultiPartException:
            if not too_large:
                raise
        if too_large:
            await self._too_large(scope, receive, send)

    @staticmethod
    async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
        await JSONResponse({"detail": "The request exceeds the configured upload size limit."}, status_code=413)(
            scope, receive, send,
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    await run_in_threadpool(auth.bootstrap_admin)
    logger.info("api_started")
    yield


app = FastAPI(
    title="PDF to Word Pro",
    description="Private, owner-scoped asynchronous document conversion.",
    version="1.0.0",
    docs_url=f"{API_PREFIX}/docs",
    redoc_url=f"{API_PREFIX}/redoc",
    swagger_ui_oauth2_redirect_url=f"{API_PREFIX}/docs/oauth2-redirect",
    openapi_url=f"{API_PREFIX}/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(RequestPolicy)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)
for router in (files.router, conversions.router, pdf.router, auth.router, admin.router, benchmark_router):
    app.include_router(router, prefix=API_PREFIX)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic error input can include credentials and untrusted document settings.
    details = [
        {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
        for item in exc.errors()
    ]
    return JSONResponse({"detail": details}, status_code=422)


@app.exception_handler(Exception)
async def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.error("api_request_failed", extra={"error_type": type(exc).__name__})
    return JSONResponse({"detail": "The service encountered an unexpected error."}, status_code=500)


@app.get(f"{API_PREFIX}/health", tags=["system"])
def health() -> JSONResponse:
    statuses = checks()
    available = healthy(statuses)
    return JSONResponse(
        {"status": "ok" if available else "degraded", "checks": statuses},
        status_code=200 if available else 503,
    )


@app.get(f"{API_PREFIX}/config", tags=["system"], response_model=ConfigView)
def config(
    _: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
) -> ConfigView:
    return effective_config(db)
