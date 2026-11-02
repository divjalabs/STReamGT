"""kit_analysis_setups: what the next run of a kit should look like, saved before the FASTQ exists

The Analyse page held all of this in browser state, so a run prepared in advance — most painfully
a 96-well plate typed by hand — was lost the moment the page was left. One row per kit, overwritten
in place.

`batches` is JSON rather than its own table: it mirrors SampleBatchIn, the plate is already only
text, and a draft needs neither ordinals nor referential integrity.

The three target FKs are ON DELETE SET NULL, unlike the plain ones on `jobs`. A job records what
actually ran and should stand in the way of deleting its project; a draft should simply forget a
target that has gone away.

Revision ID: 0015_kit_analysis_setup
Revises: 0014_kit_claim_code_sealed
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa


revision = '0015_kit_analysis_setup'
down_revision = '0014_kit_claim_code_sealed'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The create_table equivalent of the _has_column guard the add-column migrations use (0009-0014):
    # makes a re-run after a half-applied deploy a no-op rather than a duplicate-table error.
    if sa.inspect(op.get_bind()).has_table('kit_analysis_setups'):
        return

    op.create_table(
        'kit_analysis_setups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kit_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('default_population_id', sa.Integer(), nullable=True),
        sa.Column('default_study_id', sa.Integer(), nullable=True),
        sa.Column('expected_read_number', sa.BigInteger(), nullable=True),
        sa.Column('parameters', sa.JSON(), nullable=True),
        sa.Column('batches', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['kit_id'], ['kits.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['default_population_id'], ['populations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['default_study_id'], ['studies.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kit_id', name='uq_kit_analysis_setup_kit'),
    )
    op.create_index(op.f('ix_kit_analysis_setups_kit_id'), 'kit_analysis_setups', ['kit_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_kit_analysis_setups_kit_id'), table_name='kit_analysis_setups')
    op.drop_table('kit_analysis_setups')
