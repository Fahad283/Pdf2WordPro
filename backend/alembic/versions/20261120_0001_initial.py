"""Create users, private files, batches, conversions and operational settings."""

import sqlalchemy as sa
from alembic import op

revision = "20261120_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("plan", sa.String(20), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_key", sa.String(80), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(72), nullable=False, unique=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer()),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("encrypted", sa.Boolean(), nullable=False),
        sa.Column("purged_at", sa.DateTime()),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
    )
    for column in ("owner_key", "user_id", "purged_at", "expires_at", "deleted_at"):
        op.create_index(f"ix_files_{column}", "files", [column])

    op.create_table(
        "batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_key", sa.String(80), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    for column in ("owner_key", "user_id", "expires_at"):
        op.create_index(f"ix_batches_{column}", "batches", [column])

    op.create_table(
        "conversion_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_key", sa.String(80), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("batches.id", ondelete="SET NULL")),
        sa.Column("output_file_id", sa.String(36), sa.ForeignKey("files.id", ondelete="SET NULL")),
        sa.Column("tool", sa.String(40), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column("attempt", sa.String(36), nullable=False),
        sa.Column("requires_password", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
    )
    for column in ("owner_key", "user_id", "batch_id", "output_file_id", "status", "created_at", "expires_at", "deleted_at"):
        op.create_index(f"ix_conversion_jobs_{column}", "conversion_jobs", [column])
    op.create_index("ix_jobs_owner_created", "conversion_jobs", ["owner_key", "created_at"])

    op.create_table(
        "job_inputs",
        sa.Column("job_id", sa.String(36), sa.ForeignKey("conversion_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("file_id", sa.String(36), sa.ForeignKey("files.id", ondelete="RESTRICT"), nullable=False),
    )
    op.create_index("ix_job_inputs_file_id", "job_inputs", ["file_id"])

    op.create_table(
        "admin_settings",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
    )
    op.create_table(
        "usage_buckets",
        sa.Column("owner_key", sa.String(80), primary_key=True),
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    for table in ("usage_buckets", "admin_settings", "job_inputs", "conversion_jobs", "batches", "files", "users"):
        op.drop_table(table)
