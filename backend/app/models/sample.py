"""Samples (unique system IDs; names may duplicate) and their per-replicate data.

`samples` is the first-class sample entity the whole animal/matching layer hangs off. A sample
is produced by a job (ingestion provenance), belongs to a project, and carries the flags matching
needs (reliability, reference, lock). `replicate_observations` / `replicate_amplifications` mirror
the pipeline's per-well genotypes/positions tables, feeding the replicate view, plots, and
backend consensus recompute.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    String, Integer, Boolean, Float, DateTime, ForeignKey, Enum as SAEnum, func, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import Sex


class Sample(Base):
    __tablename__ = "samples"

    id: Mapped[int] = mapped_column(primary_key=True)  # the unique system ID
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    system_code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    population_id: Mapped[int | None] = mapped_column(ForeignKey("populations.id"), index=True)
    study_id: Mapped[int | None] = mapped_column(ForeignKey("studies.id"))
    kit_id: Mapped[int | None] = mapped_column(ForeignKey("kits.id"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    sample_type_id: Mapped[int | None] = mapped_column(ForeignKey("sample_types.id"))

    name: Mapped[str] = mapped_column(String(255), nullable=False)  # user-entered; NOT unique
    sex: Mapped[Sex] = mapped_column(SAEnum(Sex, name="sex"), default=Sex.unknown, nullable=False)
    sex_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Matching / QC flags (mirror tblSamples).
    discard_sample: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    animal_matchlock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_animal_reference: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    genotype_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    quality_index: Mapped[float | None] = mapped_column(Float)  # aggregate across markers
    n_replicates: Mapped[int | None] = mapped_column(Integer)

    subgroup_id: Mapped[int | None] = mapped_column(
        # use_alter breaks the samples <-> match_subgroups circular FK for create_all
        ForeignKey("match_subgroups.id", use_alter=True, name="fk_samples_subgroup"), index=True
    )  # assigned individual animal (set by matching)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_samples_job_name", "job_id", "name"),)

    consensus_genotypes: Mapped[list["ConsensusGenotype"]] = relationship(  # noqa: F821
        back_populates="sample", cascade="all, delete-orphan"
    )


class ReplicateObservation(Base):
    """One called allele in one amplification well (mirror of {kit}_genotypes.txt called rows)."""

    __tablename__ = "replicate_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    sample_id: Mapped[int] = mapped_column(
        ForeignKey("samples.id", ondelete="CASCADE"), index=True, nullable=False
    )
    marker: Mapped[str] = mapped_column(String(128), nullable=False)
    plate: Mapped[str | None] = mapped_column(String(64))
    position: Mapped[int | None] = mapped_column(Integer)
    tag_combo: Mapped[str | None] = mapped_column(String(128))
    run_name: Mapped[str | None] = mapped_column(String(128))
    read_count: Mapped[int | None] = mapped_column(Integer)
    length: Mapped[int | None] = mapped_column(Integer)
    called: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    flag: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    stutter: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sequence: Mapped[str | None] = mapped_column(String(2048))
    allele_name: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (Index("ix_replobs_sample_marker", "sample_id", "marker"),)


class ReplicateAmplification(Base):
    """One attempted amplification well (mirror of {kit}_positions.txt) — the NAmp denominator,
    including wells that produced no called allele."""

    __tablename__ = "replicate_amplifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    sample_id: Mapped[int] = mapped_column(
        ForeignKey("samples.id", ondelete="CASCADE"), index=True, nullable=False
    )
    marker: Mapped[str] = mapped_column(String(128), nullable=False)
    plate: Mapped[str | None] = mapped_column(String(64))
    position: Mapped[int | None] = mapped_column(Integer)
    tag_combo: Mapped[str | None] = mapped_column(String(128))
    run_name: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (Index("ix_replamp_sample_marker", "sample_id", "marker"),)
