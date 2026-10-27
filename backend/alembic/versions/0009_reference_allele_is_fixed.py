"""curated (pinned) reference-allele names

A fixed allele name is never reassigned when names are renormalised.

This column already exists in production: it was applied by the now-removed `app.dbupgrade`
script, which ran ahead of Alembic. The migration is written to be a no-op in that case.

Revision ID: 0009_ref_allele_is_fixed
Revises: 0008_kit_claim
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa


revision = '0009_ref_allele_is_fixed'
down_revision = '0008_kit_claim'
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if _has_column('reference_alleles', 'is_fixed'):
        return
    op.add_column(
        'reference_alleles',
        sa.Column('is_fixed', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('reference_alleles', 'is_fixed')
