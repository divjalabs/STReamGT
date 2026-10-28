"""remember which compute is running a job

An ECS task ARN (or "celery:<task id>" locally), so a stop can kill the task and the API can ask
ECS whether a job that has gone quiet is still alive.

Revision ID: 0012_job_task_arn
Revises: 0011_job_parameters
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa


revision = '0012_job_task_arn'
down_revision = '0011_job_parameters'
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if _has_column('jobs', 'task_arn'):
        return
    op.add_column('jobs', sa.Column('task_arn', sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'task_arn')
