from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = Field("sqlite:///./data/app.db", repr=False)
    redis_url: str = Field("redis://localhost:6379/0", repr=False)
    secret_key: str = Field("", repr=False)
    work_dir: Path = Path("./data/work")
    storage_dir: Path = Path("./data/objects")
    storage_backend: Literal["local", "s3"] = "local"
    s3_bucket: str = ""
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = Field(None, repr=False)
    clamav_host: str | None = None
    clamav_port: int = 3310
    clamav_required: bool = False
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8080,http://127.0.0.1:8080"
    cookie_secure: bool = False
    max_upload_mb: int = Field(50, ge=1, le=256)
    max_output_mb: int = Field(256, ge=1, le=1024)
    max_pages: int = Field(500, ge=1, le=2000)
    max_batch_files: int = Field(10, ge=1, le=30)
    retention_minutes: int = Field(60, ge=1, le=1440)
    metadata_retention_days: int = Field(30, ge=1, le=365)
    daily_conversion_limit: int = Field(40, ge=1, le=100000)
    ocr_languages: str = "eng,urd,ara"
    benchmark_artifact_days: int = Field(14, ge=1, le=90)
    benchmark_application_version: str = Field("1.0.0+bench.1", min_length=1, max_length=80)
    job_timeout_seconds: int = Field(900, ge=30, le=3600)
    celery_task_always_eager: bool = False
    admin_email: str | None = None
    admin_password: str | None = Field(None, repr=False)

    @model_validator(mode="after")
    def check_configuration(self) -> "Settings":
        if not self.secret_key:
            if self.environment == "production":
                raise ValueError("Set SECRET_KEY in production.")
            # Stable for the two local processes. Production always needs a generated secret.
            self.secret_key = "pdf-to-word-pro-local-development-only"
        if self.environment == "production":
            if len(self.secret_key) < 32 or self.secret_key == "pdf-to-word-pro-local-development-only":
                raise ValueError("Set a high-entropy SECRET_KEY of at least 32 characters.")
            if not self.cookie_secure:
                raise ValueError("Production requires COOKIE_SECURE=true and HTTPS.")
            if self.celery_task_always_eager:
                raise ValueError("Eager conversion is available in development and test only.")
            if not self.clamav_required:
                raise ValueError("Production requires CLAMAV_REQUIRED=true.")
            if self.database_url.startswith("sqlite"):
                raise ValueError("Use PostgreSQL in production.")
        if self.clamav_required and not self.clamav_host:
            raise ValueError("CLAMAV_HOST is required when CLAMAV_REQUIRED=true.")
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise ValueError("S3_BUCKET is required for S3 storage.")
        if bool(self.admin_email) != bool(self.admin_password):
            raise ValueError("Set both ADMIN_EMAIL and ADMIN_PASSWORD, or neither.")
        return self

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip().rstrip("/") for item in self.cors_origins.split(",") if item.strip()]

    @property
    def configured_languages(self) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in self.ocr_languages.split(",") if item.strip()))


@lru_cache
def get_settings() -> Settings:
    return Settings()
