"""Initial schema: repositories, investigations and the audit trail.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("snapshot_path", sa.Text(), nullable=False),
        sa.Column("commit_sha", sa.String(64)),
        sa.Column("profile", JSON, nullable=False),
        sa.Column("last_scan", JSON),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "investigations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("repository_id", sa.String(32), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("symptom", sa.Text(), nullable=False),
        sa.Column("target_test", sa.Text()),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("phase", sa.String(40), nullable=False),
        sa.Column("active_agent", sa.String(40)),
        sa.Column("verdict", sa.String(40)),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.Column("provider_note", sa.Text()),
        sa.Column("budget", JSON, nullable=False),
        sa.Column("usage", JSON, nullable=False),
        sa.Column("investigation_report", JSON),
        sa.Column("summary", JSON),
        sa.Column("root_cause", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
    )
    op.create_index("ix_investigations_repository_id", "investigations", ["repository_id"])
    op.create_index("ix_investigations_status", "investigations", ["status"])
    op.create_index("ix_investigations_created_at", "investigations", ["created_at"])
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column(
            "investigation_id", sa.String(32), sa.ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("ts", TS, nullable=False),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column("type", sa.String(60), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", JSON, nullable=False),
    )
    op.create_index("ix_events_investigation_id", "events", ["investigation_id"])
    op.create_table(
        "hypotheses",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "investigation_id", sa.String(32), sa.ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("key", sa.String(16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("suspected_locations", JSON, nullable=False),
        sa.Column("supporting_evidence", JSON, nullable=False),
        sa.Column("contradicting_evidence", JSON, nullable=False),
        sa.Column("prior", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("history", JSON, nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_hypotheses_investigation_id", "hypotheses", ["investigation_id"])
    op.create_table(
        "experiments",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "investigation_id", sa.String(32), sa.ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("key", sa.String(16), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("designed_by", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("hypothesis_keys", JSON, nullable=False),
        sa.Column("predictions", JSON, nullable=False),
        sa.Column("spec", JSON, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("outcome", sa.String(20)),
        sa.Column("result", JSON),
        sa.Column("evaluation", JSON),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
    )
    op.create_index("ix_experiments_investigation_id", "experiments", ["investigation_id"])
    op.create_table(
        "patches",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "investigation_id", sa.String(32), sa.ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("key", sa.String(16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("hypothesis_key", sa.String(16)),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("edits", JSON, nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("files_changed", JSON, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("verification", JSON),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("review_note", sa.Text()),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_patches_investigation_id", "patches", ["investigation_id"])
    op.create_table(
        "model_calls",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "investigation_id", sa.String(32), sa.ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column("task", sa.String(60), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("tokens_estimated", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_model_calls_investigation_id", "model_calls", ["investigation_id"])
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("value", JSON),
        sa.Column("updated_at", TS, nullable=False),
    )


def downgrade() -> None:
    for table in ("app_settings", "model_calls", "patches", "experiments", "hypotheses", "events", "investigations",
                  "repositories"):
        op.drop_table(table)
