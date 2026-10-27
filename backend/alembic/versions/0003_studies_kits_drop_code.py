"""studies_kits_and_drop_population_code

Add the study<->kit attachment table and drop the unused populations.code column.

Revision ID: 0003_studies_kits
Revises: 8e21237a1d0b
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa


revision = '0003_studies_kits'
down_revision = '8e21237a1d0b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'study_kits',
        sa.Column('study_id', sa.Integer(), nullable=False),
        sa.Column('kit_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['study_id'], ['studies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['kit_id'], ['kits.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('study_id', 'kit_id'),
    )
    op.drop_column('populations', 'code')


def downgrade() -> None:
    op.add_column('populations', sa.Column('code', sa.String(length=64), nullable=True))
    op.drop_table('study_kits')
