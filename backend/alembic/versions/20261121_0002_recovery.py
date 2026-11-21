"""Track independently recoverable job dispatches and pending objects."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_0002"
down_revision = "20261120_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversion_jobs", sa.Column("dispatched_at", sa.DateTime()))
    op.create_index("ix_conversion_jobs_dispatched_at", "conversion_jobs", ["dispatched_at"])
    op.create_table(
        "staged_objects",
        sa.Column("storage_key", sa.String(72), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_staged_objects_created_at", "staged_objects", ["created_at"])


def downgrade() -> None:
    op.drop_table("staged_objects")
    op.drop_index("ix_conversion_jobs_dispatched_at", table_name="conversion_jobs")
    op.drop_column("conversion_jobs", "dispatched_at")
