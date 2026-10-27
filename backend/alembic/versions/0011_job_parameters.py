"""per-run pipeline parameters

The allele-calling thresholds a job actually ran with, so a result can be explained later and a
recompute can reproduce it.

Already present in production via the removed `app.dbupgrade` script — no-op there.

Revision ID: 0011_job_parameters
Revises: 0010_project_species
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa


revision = '0011_job_parameters'
down_revision = '0010_project_species'
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    # (The `control_kind` enum values that app.dbupgrade also applied are already added by
    # migration 0006 — dbupgrade only repeated them because it bypassed Alembic entirely.)
    if _has_column('jobs', 'parameters'):
        return
    op.add_column('jobs', sa.Column('parameters', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'parameters')
