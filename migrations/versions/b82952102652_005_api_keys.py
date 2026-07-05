"""005 api keys

Revision ID: b82952102652
Revises: ae2f4b892fce
Create Date: 2026-07-05 19:18:14.826526
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b82952102652"
down_revision: Union[str, None] = "ae2f4b892fce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("encrypted_key", sa.String(), nullable=False),
        sa.Column("last4", sa.String(length=4), nullable=False),
        sa.Column(
            "set_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "provider"),
    )


def downgrade() -> None:
    op.drop_table("api_keys")
