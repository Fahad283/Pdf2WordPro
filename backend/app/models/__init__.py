from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow


def new_id() -> str:
    return str(uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="active")
    role: Mapped[str] = mapped_column(String(20), default="user")
    plan: Mapped[str] = mapped_column(String(20), default="free")
    session_version: Mapped[int] = mapped_column(Integer, default=0)


class FileRecord(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_key: Mapped[str] = mapped_column(String(80), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(72), unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(100))
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    kind: Mapped[str] = mapped_column(String(12), default="input")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_key: Mapped[str] = mapped_column(String(80), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Job(Base):
    __tablename__ = "conversion_jobs"
    __table_args__ = (Index("ix_jobs_owner_created", "owner_key", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_key: Mapped[str] = mapped_column(String(80), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id", ondelete="SET NULL"), index=True)
    output_file_id: Mapped[str | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"), index=True)
    tool: Mapped[str] = mapped_column(String(40))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    attempt: Mapped[str] = mapped_column(String(36), default=new_id)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    requires_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)

    inputs: Mapped[list["JobInput"]] = relationship(order_by="JobInput.position", lazy="selectin")
    output: Mapped[FileRecord | None] = relationship(lazy="selectin")


class JobInput(Base):
    __tablename__ = "job_inputs"

    job_id: Mapped[str] = mapped_column(ForeignKey("conversion_jobs.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="RESTRICT"), index=True)
    file: Mapped[FileRecord] = relationship(lazy="joined")


class AdminSetting(Base):
    __tablename__ = "admin_settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict | list | int] = mapped_column(JSON)


class UsageBucket(Base):
    __tablename__ = "usage_buckets"

    owner_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)


class StagedObject(Base):
    __tablename__ = "staged_objects"

    storage_key: Mapped[str] = mapped_column(String(72), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
