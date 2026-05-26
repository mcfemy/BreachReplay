"""Add pgvector embedding column to scenarios table

Revision ID: 0005_scenario_embeddings
Revises: 0004_expand_participant_roles
Create Date: 2026-05-26

Adds a 384-dimensional vector column (BAAI/bge-small-en-v1.5 output) and
an HNSW index for fast approximate nearest-neighbour cosine similarity search.

HNSW is preferred over IVFFlat for datasets < 1M rows because it does not
require a training step and delivers higher recall at the same query speed.
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0005_scenario_embeddings"
down_revision = "0004_expand_participant_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension (idempotent — safe if already enabled)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Add the embedding column (nullable so existing rows are not blocked)
    op.add_column("scenarios", sa.Column("embedding", Vector(384), nullable=True))

    # HNSW index for cosine similarity (<=> operator)
    # m=16, ef_construction=64 are good defaults for recall vs. build-time trade-off
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_scenarios_embedding_hnsw "
        "ON scenarios USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_scenarios_embedding_hnsw")
    op.drop_column("scenarios", "embedding")
