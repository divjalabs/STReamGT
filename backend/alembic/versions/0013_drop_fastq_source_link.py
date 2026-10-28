"""drop the unused `link` value from the fastq_source enum

`link` meant "fetch the FASTQ pair from this URL", staged inside the pipeline task with
urllib — the task that holds S3 write access and the app's secrets, and urllib honours file://
as well as http://. It was never used: production had 7 `server` and 2 `upload`, zero `link`.

PostgreSQL cannot remove a value from an enum, so the type is rebuilt: a new type with the two
remaining values, the column cast across, then the old type dropped and the new one renamed into
its place. That whole sequence is transactional, so a failure leaves the original untouched.

Does nothing on SQLite, where the tests build the schema from the Python enum directly.

Revision ID: 0013_drop_fastq_source_link
Revises: 0012_job_task_arn
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa


revision = '0013_drop_fastq_source_link'
down_revision = '0012_job_task_arn'
branch_labels = None
depends_on = None


def _enum_labels(name: str) -> set[str]:
    """The values of a native enum type; empty on a dialect that has none (SQLite) — which is
    also the signal to do nothing, the same role `_has_column` plays in 0009-0012."""
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return set()
    return set(bind.execute(sa.text(
        "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
        "WHERE t.typname = :name"
    ), {"name": name}).scalars())


def upgrade() -> None:
    if 'link' not in _enum_labels('fastq_source'):
        return  # SQLite, or already applied

    bind = op.get_bind()
    stragglers = bind.execute(
        sa.text("SELECT count(*) FROM jobs WHERE fastq_source = 'link'")
    ).scalar_one()
    if stragglers:
        # Refuse rather than guess. Those rows' refs are URLs, which nothing can stage any more,
        # so converting them silently would turn a visible problem into a confusing one. Without
        # this check the cast below fails with a bare "invalid input value for enum".
        raise RuntimeError(
            f"{stragglers} job(s) still use fastq_source='link'. This migration will not guess "
            "what to do with them. Look at them first:\n"
            "  SELECT id, public_id, fastq1_ref FROM jobs WHERE fastq_source='link';\n"
            "then either delete them or set them to 'server', and run this again."
        )

    # The column's default lives in the model, not the database — but ALTER COLUMN TYPE cannot
    # carry a default across types, so drop it blind. A no-op today; the difference between a
    # clean migration and a failed one if a default is ever added.
    op.execute("ALTER TABLE jobs ALTER COLUMN fastq_source DROP DEFAULT")
    # Only left behind by an earlier run that died mid-way.
    op.execute("DROP TYPE IF EXISTS fastq_source_new")

    op.execute("CREATE TYPE fastq_source_new AS ENUM ('upload', 'server')")
    # ::text:: is required: there is no cast between two enum types. NOT NULL and every existing
    # value survive the change.
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN fastq_source TYPE fastq_source_new "
        "USING fastq_source::text::fastq_source_new"
    )
    op.execute("DROP TYPE fastq_source")
    op.execute("ALTER TYPE fastq_source_new RENAME TO fastq_source")


def downgrade() -> None:
    labels = _enum_labels('fastq_source')
    if not labels or 'link' in labels:
        return  # SQLite, or already reversed

    # Adding the value back restores the original type exactly, with no second type swap.
    # ADD VALUE cannot run inside a transaction block, hence the autocommit block (as in 0006).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE fastq_source ADD VALUE IF NOT EXISTS 'link'")
