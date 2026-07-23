"""kit_reads: one current server-side FASTQ pair per kit

Revision ID: 0007_kit_reads
Revises: 0006_controls
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa


revision = '0007_kit_reads'
down_revision = '0006_controls'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'kit_reads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kit_id', sa.Integer(), nullable=False),
        sa.Column('fastq1_key', sa.String(length=512), nullable=False),
        sa.Column('fastq2_key', sa.String(length=512), nullable=False),
        sa.Column('fastq1_name', sa.String(length=255), nullable=True),
        sa.Column('fastq2_name', sa.String(length=255), nullable=True),
        sa.Column('size1', sa.Integer(), nullable=True),
        sa.Column('size2', sa.Integer(), nullable=True),
        sa.Column('uploaded_by', sa.Integer(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['kit_id'], ['kits.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kit_id', name='uq_kit_reads_kit'),
    )
    op.create_index(op.f('ix_kit_reads_kit_id'), 'kit_reads', ['kit_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_kit_reads_kit_id'), table_name='kit_reads')
    op.drop_table('kit_reads')
