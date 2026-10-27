"""kit claim codes: self-service kit access

Adds a claim code (stored as keyed HMAC) + claimer to kits.

Revision ID: 0008_kit_claim
Revises: 0007_kit_reads
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa


revision = '0008_kit_claim'
down_revision = '0007_kit_reads'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('kits', sa.Column('claim_code_hmac', sa.String(length=64), nullable=True))
    op.add_column('kits', sa.Column('claimed_by', sa.Integer(), nullable=True))
    op.add_column('kits', sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key('fk_kits_claimed_by', 'kits', 'users', ['claimed_by'], ['id'])
    op.create_index('ix_kits_claim_code_hmac', 'kits', ['claim_code_hmac'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_kits_claim_code_hmac', table_name='kits')
    op.drop_constraint('fk_kits_claimed_by', 'kits', type_='foreignkey')
    op.drop_column('kits', 'claimed_at')
    op.drop_column('kits', 'claimed_by')
    op.drop_column('kits', 'claim_code_hmac')
