"""animal_overrides

Persistent per-animal manual edits (reliably-genotyped, confirmed, notes), keyed by the stable
reference sample so they survive full population reruns.

Revision ID: 0004_animal_overrides
Revises: 0003_studies_kits
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa


revision = '0004_animal_overrides'
down_revision = '0003_studies_kits'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'animal_overrides',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('population_id', sa.Integer(), nullable=False),
        sa.Column('reference_sample_id', sa.Integer(), nullable=False),
        sa.Column('reliably_genotyped', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('notes', sa.String(length=2048), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['population_id'], ['populations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reference_sample_id'], ['samples.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reference_sample_id', name='uq_animal_override_reference'),
    )
    op.create_index(op.f('ix_animal_overrides_population_id'), 'animal_overrides', ['population_id'])
    op.create_index(op.f('ix_animal_overrides_reference_sample_id'), 'animal_overrides', ['reference_sample_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_animal_overrides_reference_sample_id'), table_name='animal_overrides')
    op.drop_index(op.f('ix_animal_overrides_population_id'), table_name='animal_overrides')
    op.drop_table('animal_overrides')
