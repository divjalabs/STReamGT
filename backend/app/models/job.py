from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    String,
    Integer,
    Float,
    BigInteger,
    DateTime,
    ForeignKey,
    Enum as SAEnum,
    JSON,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import JobStatus, FastqSource, ResultKind


class Job(Base):
    """A genotyping run: one kit + one FASTQ pair + N sample batches.

    The FASTQ pair lives here (job-level) because every generated input.tsv row
    repeats the same reads; batches differ only by sample sheet + tag selection.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    kit_id: Mapped[int] = mapped_column(ForeignKey("kits.id"), index=True, nullable=False)

    # Optional project the job's samples are ingested into (animal/matching layer).
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    default_population_id: Mapped[int | None] = mapped_column(ForeignKey("populations.id"))
    default_study_id: Mapped[int | None] = mapped_column(ForeignKey("studies.id"))

    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="job_status"), default=JobStatus.queued, index=True, nullable=False
    )

    # FASTQ pair (shared by all batches). Meaning of *_ref depends on fastq_source.
    fastq_source: Mapped[FastqSource] = mapped_column(
        SAEnum(FastqSource, name="fastq_source"), default=FastqSource.upload, nullable=False
    )
    fastq1_ref: Mapped[str | None] = mapped_column(String(1024))  # S3 key / server path / URL
    fastq2_ref: Mapped[str | None] = mapped_column(String(1024))

    # Pipeline params.
    min_identity: Mapped[float] = mapped_column(Float, default=0.9, nullable=False)
    min_overlap: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    expected_read_number: Mapped[int | None] = mapped_column(BigInteger)
    observed_read_count: Mapped[int | None] = mapped_column(BigInteger)  # counted at pre-flight
    reads_confirmed: Mapped[bool] = mapped_column(default=False, nullable=False)  # user OK'd low reads

    # Execution bookkeeping.
    storage_prefix: Mapped[str | None] = mapped_column(String(512))  # s3 prefix for results
    nextflow_run_name: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(String(4096))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="jobs")  # noqa: F821
    kit: Mapped["Kit"] = relationship()  # noqa: F821
    batches: Mapped[list["SampleBatch"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="SampleBatch.ordinal"
    )
    result_files: Mapped[list["ResultFile"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class SampleBatch(Base):
    """One amplification plate: a sample sheet + a selected subset of PP tag columns.

    Becomes one row of the generated input.tsv.
    """

    __tablename__ = "sample_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. HRM01

    # Samples: either an uploaded .xlsx (S3 key) or pasted text (positions/names).
    sample_sheet_key: Mapped[str | None] = mapped_column(String(512))
    sample_names_text: Mapped[str | None] = mapped_column(String(65536))

    # Optional per-batch species (from the excalidraw dropdown). Defaults to the kit's.
    species: Mapped[str | None] = mapped_column(String(64))

    # Selected PP columns, e.g. ["PP1","PP2","PP3","PP4"]. Serialized to "PP1-PP4" for the TSV.
    selected_tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    job: Mapped["Job"] = relationship(back_populates="batches")


class ResultFile(Base):
    """An output artifact produced by a finished job, stored in S3."""

    __tablename__ = "result_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True, nullable=False)
    kind: Mapped[ResultKind] = mapped_column(SAEnum(ResultKind, name="result_kind"), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped["Job"] = relationship(back_populates="result_files")
