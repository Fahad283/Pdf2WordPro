"""Benchmark metadata lives separately from private PDF and DOCX objects."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, utcnow
from app.models import new_id


class BenchmarkDataset(Base):
    __tablename__ = "benchmark_datasets"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(16), default="ready")
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BenchmarkDocument(Base):
    __tablename__ = "benchmark_documents"
    __table_args__ = (UniqueConstraint("dataset_id", "case_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("benchmark_datasets.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(String(48))
    category: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String(500))
    behavior: Mapped[str] = mapped_column(String(16))
    expected_error: Mapped[str | None] = mapped_column(String(240))
    source_key: Mapped[str] = mapped_column(String(48))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    ground_truth: Mapped[dict] = mapped_column(JSON)
    settings: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BenchmarkReference(Base):
    __tablename__ = "benchmark_references"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("benchmark_documents.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(48))
    sha256: Mapped[str] = mapped_column(String(64))
    source_sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("benchmark_datasets.id", ondelete="RESTRICT"), index=True)
    dataset_version: Mapped[str] = mapped_column(String(60))
    dataset_sha256: Mapped[str] = mapped_column(String(64))
    application_version: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), index=True, default="queued")
    config: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[dict | None] = mapped_column(JSON)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("benchmark_runs.id", ondelete="SET NULL"))
    total: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class BenchmarkResult(Base):
    __tablename__ = "benchmark_results"
    __table_args__ = (UniqueConstraint("run_id", "case_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("benchmark_runs.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("benchmark_documents.id", ondelete="RESTRICT"))
    reference_id: Mapped[str | None] = mapped_column(ForeignKey("benchmark_references.id", ondelete="RESTRICT"))
    case_id: Mapped[str] = mapped_column(String(48))
    category: Mapped[str] = mapped_column(String(60))
    behavior: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    conversion_ok: Mapped[bool | None] = mapped_column(Boolean)
    score: Mapped[float | None] = mapped_column(Float)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    details: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime)
    artifact_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
