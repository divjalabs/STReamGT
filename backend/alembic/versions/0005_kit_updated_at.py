"""kit_updated_at

Add kits.updated_at, bumped on every row update (in practice the kit's last status change).
Surfaced on the client "My kits" list. Existing rows are backfilled to created_at.

Revision ID: 0005_kit_updated_at
Revises: 0004_animal_overrides
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = '0005_kit_updated_at'
down_revision = '0004_animal_overrides'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'kits',
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    # Backfill existing kits so the column reflects a sensible timestamp, not the migration time.
    op.execute('UPDATE kits SET updated_at = created_at')


def downgrade() -> None:
    op.drop_column('kits', 'updated_at')
