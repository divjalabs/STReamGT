"""ORM models. Importing this package registers all tables on Base.metadata."""
from app.models.enums import (
    UserRole,
    JobStatus,
    PrimerType,
    ControlKind,
    FastqSource,
    ResultKind,
)
from app.models.user import User
from app.models.kit import Kit, Primer, TagColumn, Control
from app.models.job import Job, SampleBatch, ResultFile

__all__ = [
    "UserRole",
    "JobStatus",
    "PrimerType",
    "ControlKind",
    "FastqSource",
    "ResultKind",
    "User",
    "Kit",
    "Primer",
    "TagColumn",
    "Control",
    "Job",
    "SampleBatch",
    "ResultFile",
]
