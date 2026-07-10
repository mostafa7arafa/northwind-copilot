"""007 turn feedback and golden examples

Revision ID: 8e47b15f5821
Revises: 503821bd43e6
Create Date: 2026-07-06 04:50:18.234278
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e47b15f5821'
down_revision: Union[str, None] = '503821bd43e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('turn_feedback',
    sa.Column('turn_id', sa.String(length=36), nullable=False),
    sa.Column('org_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('vote', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['turn_id'], ['turns.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('turn_id')
    )
    with op.batch_alter_table('turn_feedback', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_turn_feedback_org_id'), ['org_id'], unique=False)

    op.create_table('golden_examples',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('dataset_id', sa.String(length=36), nullable=False),
    sa.Column('org_id', sa.String(length=36), nullable=False),
    sa.Column('source_turn_id', sa.String(length=36), nullable=True),
    sa.Column('question', sa.String(), nullable=False),
    sa.Column('sql', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_turn_id'], ['turns.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('golden_examples', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_golden_examples_dataset_id'), ['dataset_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('golden_examples', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_golden_examples_dataset_id'))

    op.drop_table('golden_examples')
    with op.batch_alter_table('turn_feedback', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_turn_feedback_org_id'))

    op.drop_table('turn_feedback')
