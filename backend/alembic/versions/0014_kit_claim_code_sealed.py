"""keep an encrypted copy of a kit's claim code, so a sticker sheet can be reprinted

Only the code's keyed HMAC was stored, which is one-way: the plaintext existed in exactly one
HTTP response and was then gone. Losing the spreadsheet before printing meant issuing new codes
and invalidating every sticker already in the post.

This column holds the same code sealed with a key derived from CLAIM_CODE_KEY
(app/services/code_vault.py), so an admin can reprint. It is cleared when the kit is claimed.

Nothing is backfilled — codes issued before this are unrecoverable by design, and those kits are
simply absent from the sheet until their code is regenerated.

Revision ID: 0014_kit_claim_code_sealed
Revises: 0013_drop_fastq_source_link
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa


revision = '0014_kit_claim_code_sealed'
down_revision = '0013_drop_fastq_source_link'
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if _has_column('kits', 'claim_code_sealed'):
        return
    # 255 is roomy: a Fernet token over a 19-character code is ~120 characters.
    op.add_column('kits', sa.Column('claim_code_sealed', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('kits', 'claim_code_sealed')
