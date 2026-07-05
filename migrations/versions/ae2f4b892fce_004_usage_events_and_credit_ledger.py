"""004 usage events and credit ledger

Revision ID: ae2f4b892fce
Revises: d13b693b1299
Create Date: 2026-07-05 19:18:13.709846
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ae2f4b892fce"
down_revision: Union[str, None] = "d13b693b1299"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("turn_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("credits", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("byok", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("usage_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_usage_events_org_id"), ["org_id"], unique=False
        )

    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("delta", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("balance_after", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("credit_ledger", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_credit_ledger_org_id"), ["org_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("credit_ledger", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_credit_ledger_org_id"))

    op.drop_table("credit_ledger")
    with op.batch_alter_table("usage_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_usage_events_org_id"))

    op.drop_table("usage_events")
