"""Phase 4 beat-email retention loop — consent/unsubscribe foundation.

Adds per-user beat-notification opt-out, a stable email-unsubscribe token,
and first-use racing/share notice acknowledgment (no email-sending yet).

Revision ID: 0043_beat_notification_consent
Revises: 0042_log4shell_notification_matrix
Create Date: 2026-08-27 00:00:00.000000
"""
from __future__ import annotations

import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0043_beat_notification_consent"
down_revision: Union[str, None] = "0042_log4shell_notification_matrix"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_unsubscribe_tokens(connection) -> None:
    rows = connection.execute(sa.text("SELECT id FROM users")).fetchall()
    for (user_id,) in rows:
        token = secrets.token_urlsafe(32)
        connection.execute(
            sa.text(
                "UPDATE users SET email_unsubscribe_token = :token WHERE id = :id"
            ),
            {"token": token, "id": user_id},
        )


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "beat_notifications_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch_op.add_column(
            sa.Column("email_unsubscribe_token", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "has_acknowledged_racing_notice",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    connection = op.get_bind()
    _backfill_unsubscribe_tokens(connection)

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("email_unsubscribe_token", nullable=False)
        batch_op.create_index(
            "ix_users_email_unsubscribe_token",
            ["email_unsubscribe_token"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_email_unsubscribe_token")
        batch_op.drop_column("has_acknowledged_racing_notice")
        batch_op.drop_column("email_unsubscribe_token")
        batch_op.drop_column("beat_notifications_enabled")
