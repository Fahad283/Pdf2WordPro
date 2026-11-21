import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


Language = Annotated[str, Field(pattern=r"^[a-z]{3}(?:_[a-z]{3,8})?$")]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ToolSettings(InputModel):
    mode: Literal["editable", "flowing", "visual"] = "editable"
    ocr: Literal["auto", "force", "off"] = "auto"
    languages: list[Language] = Field(default_factory=lambda: ["eng"], min_length=1, max_length=8)
    pages: str | None = Field(None, max_length=1500)
    preserve_images: bool = True
    preserve_tables: bool = True
    preserve_columns: bool = True
    preserve_headers_footers: bool = True
    preserve_hyperlinks: bool = True
    preserve_page_size: bool = True
    preserve_page_breaks: bool = True
    password: str | None = Field(None, max_length=128, repr=False)
    validate_render: bool = True
    rotation: Literal[90, 180, 270] = 90
    compression: Literal["lossless", "balanced", "strong"] = "balanced"
    text: str | None = Field(None, max_length=120)
    dpi: int = Field(150, ge=72, le=300)
    split_mode: Literal["pages", "ranges"] = "pages"
    start_number: int = Field(1, ge=1, le=1000000)

    @field_validator("languages")
    @classmethod
    def unique_languages(cls, languages: list[str]) -> list[str]:
        if len(set(languages)) != len(languages):
            raise ValueError("Select each OCR language only once.")
        return languages

    @field_validator("password")
    @classmethod
    def valid_password(cls, password: str | None) -> str | None:
        if password and "\x00" in password:
            raise ValueError("PDF passwords cannot contain a NUL character.")
        return password


class JobRequest(InputModel):
    tool: str = Field("pdf-to-word", min_length=1, max_length=40, pattern=r"^[a-z0-9-]+$")
    file_ids: list[UUID] = Field(min_length=1, max_length=30)
    settings: ToolSettings = Field(default_factory=ToolSettings)

    @field_validator("file_ids")
    @classmethod
    def unique_files(cls, files: list[UUID]) -> list[UUID]:
        if len(set(files)) != len(files):
            raise ValueError("Select each uploaded file only once.")
        return files


class RetryRequest(InputModel):
    password: str | None = Field(None, max_length=128, repr=False)

    @field_validator("password")
    @classmethod
    def valid_password(cls, password: str | None) -> str | None:
        return ToolSettings.valid_password(password)


class InspectRequest(InputModel):
    file_id: UUID


class OCRRequest(InputModel):
    file_id: UUID
    settings: ToolSettings = Field(default_factory=ToolSettings)


class Credentials(InputModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128, repr=False)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or any(ord(char) < 32 for char in email):
            raise ValueError("Enter a valid email address.")
        return email


class ConfigView(BaseModel):
    max_upload_mb: int = Field(ge=1, le=256)
    max_pages: int = Field(ge=1, le=2000)
    max_batch_files: int = Field(ge=1, le=30)
    retention_minutes: int = Field(ge=1, le=1440)
    ocr_languages: list[Language] = Field(min_length=1, max_length=30)
    daily_conversion_limit: int = Field(ge=1, le=100000)


class ConfigPatch(InputModel):
    max_upload_mb: int | None = Field(None, ge=1, le=256)
    max_pages: int | None = Field(None, ge=1, le=2000)
    max_batch_files: int | None = Field(None, ge=1, le=30)
    retention_minutes: int | None = Field(None, ge=1, le=1440)
    ocr_languages: list[Language] | None = Field(None, min_length=1, max_length=30)
    daily_conversion_limit: int | None = Field(None, ge=1, le=100000)


class UserPatch(InputModel):
    status: Literal["active", "suspended"] | None = None
    plan: Literal["free", "premium"] | None = None


class FileView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_filename: str
    size_bytes: int
    page_count: int | None
    mime_type: str
    encrypted: bool
    created_at: datetime
    expires_at: datetime

    @field_serializer("created_at", "expires_at")
    def utc_datetime(self, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC)


class JobView(BaseModel):
    id: str
    batch_id: str | None
    tool: str
    input_files: list[FileView]
    status: Literal["queued", "processing", "completed", "failed", "cancelled"]
    progress: int
    error: str | None
    warnings: list[str]
    metrics: dict
    created_at: datetime
    expires_at: datetime
    output_filename: str | None

    @field_serializer("created_at", "expires_at")
    def utc_datetime(self, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC)


class BatchView(BaseModel):
    id: str
    jobs: list[JobView]


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: Literal["user", "admin"]
    plan: Literal["free", "premium"]
    status: Literal["active", "suspended"]
