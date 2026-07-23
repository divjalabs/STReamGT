"""controls: plate positions, types, templates, sample control flags

Adds position-based controls (well + resolved name) to `controls`, three new control types to the
`control_kind` enum, a reusable `control_templates` table, and `is_control`/`control_type` flags on
`samples` (so controls are excluded from matching/QC and badged in the UI).

Revision ID: 0006_controls
Revises: 0005_kit_updated_at
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0006_controls'
down_revision = '0005_kit_updated_at'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New control types (own transaction so the values are usable afterwards; PG-only).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE control_kind ADD VALUE IF NOT EXISTS 'sequencing'")
        op.execute("ALTER TYPE control_kind ADD VALUE IF NOT EXISTS 'pcr'")
        op.execute("ALTER TYPE control_kind ADD VALUE IF NOT EXISTS 'extraction'")

    # Position-based control fields; name_pattern becomes optional.
    op.add_column('controls', sa.Column('position', sa.String(length=8), nullable=True))
    op.add_column('controls', sa.Column('name', sa.String(length=255), nullable=True))
    op.alter_column('controls', 'name_pattern', existing_type=sa.String(length=128), nullable=True)

    # Sample control flags (reuse the existing control_kind enum type).
    control_kind = postgresql.ENUM(
        'positive', 'sequencing', 'pcr', 'extraction', 'negative',
        name='control_kind', create_type=False,
    )
    op.add_column('samples', sa.Column(
        'is_control', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('samples', sa.Column('control_type', control_kind, nullable=True))

    # Reusable control-position templates.
    op.create_table(
        'control_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('positions', sa.JSON(), nullable=False, server_default='[]'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_control_template_name'),
    )


def downgrade() -> None:
    op.drop_table('control_templates')
    op.drop_column('samples', 'control_type')
    op.drop_column('samples', 'is_control')
    op.alter_column('controls', 'name_pattern', existing_type=sa.String(length=128), nullable=False)
    op.drop_column('controls', 'name')
    op.drop_column('controls', 'position')
    # Enum values are intentionally left in place (PostgreSQL cannot drop enum values).
