"""Consensus genotypes (one row per Sample x Marker; mirrors atblConsensusGenotypes), the
per-project reference-allele catalog (name stability across libraries), and an edit audit log.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    String, Integer, Boolean, Float, DateTime, ForeignKey, Enum as SAEnum,
    UniqueConstraint, Index, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import ConsensusSource


class ConsensusGenotype(Base):
    __tablename__ = "consensus_genotypes"

    id: Mapped[int] = mapped_column(primary_key=True)
    sample_id: Mapped[int] = mapped_column(
        ForeignKey("samples.id", ondelete="CASCADE"), index=True, nullable=False
    )
    marker: Mapped[str] = mapped_column(String(128), nullable=False)

    # Display names (Length[_Variant]); the sequence-backed identity is allele*_id below.
    allele1: Mapped[str | None] = mapped_column(String(64))
    allele2: Mapped[str | None] = mapped_column(String(64))
    allele3: Mapped[str | None] = mapped_column(String(64))
    allele4: Mapped[str | None] = mapped_column(String(64))
    # An allele IS its sequence: these FKs point at reference_alleles (keyed by marker+sequence).
    # Consensus and matching operate on this identity, never on the name string.
    allele1_id: Mapped[int | None] = mapped_column(ForeignKey("reference_alleles.id"))
    allele2_id: Mapped[int | None] = mapped_column(ForeignKey("reference_alleles.id"))
    allele3_id: Mapped[int | None] = mapped_column(ForeignKey("reference_alleles.id"))
    allele4_id: Mapped[int | None] = mapped_column(ForeignKey("reference_alleles.id"))
    ncnf_a1: Mapped[int | None] = mapped_column(Integer)
    ncnf_a2: Mapped[int | None] = mapped_column(Integer)
    confirmed_alleles: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    unconfirmed_alleles: Mapped[str] = mapped_column(String(512), default="", nullable=False)

    n_amp: Mapped[int | None] = mapped_column(Integer)
    n_amp_ok: Mapped[int | None] = mapped_column(Integer)
    success_rate: Mapped[float | None] = mapped_column(Float)
    ado: Mapped[int | None] = mapped_column(Integer)
    ado_rate: Mapped[float | None] = mapped_column(Float)
    quality_index: Mapped[float | None] = mapped_column(Float)
    false_alleles: Mapped[int | None] = mapped_column(Integer)
    reads_per_amp: Mapped[int | None] = mapped_column(Integer)
    sd_reads_per_amp: Mapped[float | None] = mapped_column(Float)

    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[ConsensusSource] = mapped_column(
        SAEnum(ConsensusSource, name="consensus_source"),
        default=ConsensusSource.pipeline, nullable=False,
    )
    edited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("sample_id", "marker", name="uq_consensus_sample_marker"),
    )

    sample: Mapped["Sample"] = relationship(back_populates="consensus_genotypes")  # noqa: F821


class ConsensusEditLog(Base):
    __tablename__ = "consensus_edit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    consensus_id: Mapped[int] = mapped_column(
        ForeignKey("consensus_genotypes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str | None] = mapped_column(String(512))
    new_value: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReferenceAllele(Base):
    """Allele-name catalog scoped per project (mirrors atblNGSImportAlleles).

    AlleleName = Length[_Variant]. Kept per project so names stay stable across libraries;
    on re-ingest existing variant/allele_name are preserved.
    """

    __tablename__ = "reference_alleles"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    marker: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence: Mapped[str] = mapped_column(String(2048), nullable=False)
    length: Mapped[int | None] = mapped_column(Integer)
    variant: Mapped[int | None] = mapped_column(Integer)
    allele_name: Mapped[str] = mapped_column(String(64), nullable=False)
    n: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("project_id", "marker", "sequence", name="uq_refallele_proj_marker_seq"),
        Index("ix_refallele_proj_marker_name", "project_id", "marker", "allele_name"),
    )
