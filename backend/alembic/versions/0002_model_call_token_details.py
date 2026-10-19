"""Record cached and reasoning tokens per model call.

Revision ID: 0002_model_call_token_details
Revises: 0001_initial
Create Date: 2026-10-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_model_call_token_details"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_calls", sa.Column("cached_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("model_calls", sa.Column("reasoning_tokens", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("model_calls", "reasoning_tokens")
    op.drop_column("model_calls", "cached_tokens")
