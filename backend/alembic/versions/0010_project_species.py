"""one species per project

Backfills from the project's existing samples where they all agree on a species; projects that
mix species (or have no samples yet) are left NULL for an admin to set.

Already present in production via the removed `app.dbupgrade` script — no-op there.

Revision ID: 0010_project_species
Revises: 0009_ref_allele_is_fixed
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa


revision = '0010_project_species'
down_revision = '0009_ref_allele_is_fixed'
branch_labels = None
depends_on = None

BACKFILL = """
UPDATE projects p SET species = sub.sp FROM (
    SELECT s.project_id, MIN(k.species) AS sp
    FROM samples s JOIN kits k ON k.id = s.kit_id
    WHERE k.species IS NOT NULL
    GROUP BY s.project_id
    HAVING COUNT(DISTINCT k.species) = 1
) sub WHERE p.id = sub.project_id AND p.species IS NULL
"""


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if _has_column('projects', 'species'):
        return
    op.add_column('projects', sa.Column('species', sa.String(length=128), nullable=True))
    op.execute(BACKFILL)


def downgrade() -> None:
    op.drop_column('projects', 'species')
