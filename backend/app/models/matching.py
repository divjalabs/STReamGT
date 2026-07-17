"""Matching engine tables: per-population allele frequencies + PI/PIsib, the settings row of
thresholds, matching runs, pairwise matches, and the subgroup (= individual animal) / supergroup
(QC cluster) grouping. Populated by the M3 matching service; created now so the schema is complete.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    String, Integer, Boolean, Float, DateTime, ForeignKey, Enum as SAEnum, JSON, Table, Column,
    UniqueConstraint, Index, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import Sex, RunStatus, MatchTier, MismatchMetric, MatchingMode


class PopulationMarker(Base):
    """Per-population per-marker summary + probability of identity (Waits et al. 2001).
    `excluded` = user-set locus exclusion from matching (preserved across recompute)."""

    __tablename__ = "population_markers"

    id: Mapped[int] = mapped_column(primary_key=True)
    population_id: Mapped[int] = mapped_column(
        ForeignKey("populations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    marker: Mapped[str] = mapped_column(String(128), nullable=False)
    n_samples: Mapped[int | None] = mapped_column(Integer)
    n_alleles: Mapped[int | None] = mapped_column(Integer)
    effective_alleles: Mapped[float | None] = mapped_column(Float)  # Ae = 1 / sum(pi^2)
    pi: Mapped[float | None] = mapped_column(Float)
    pi_sib: Mapped[float | None] = mapped_column(Float)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("population_id", "marker", name="uq_popmarker_pop_marker"),)


class PopulationAlleleFrequency(Base):
    __tablename__ = "population_allele_frequencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    population_id: Mapped[int] = mapped_column(
        ForeignKey("populations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    marker: Mapped[str] = mapped_column(String(128), nullable=False)
    allele_name: Mapped[str] = mapped_column(String(64), nullable=False)
    observations: Mapped[int | None] = mapped_column(Integer)
    frequency: Mapped[float | None] = mapped_column(Float)  # obs / (2 * n_samples)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("population_id", "marker", "allele_name", name="uq_popfreq_pop_marker_al"),
    )


class MatchingSettings(Base):
    """Threshold set (mirrors the MisBase Two-Phase Matching Setup dialog) + the Pirog-derived
    min-shared-loci gate and the flat/decomposed + optional-PI toggles. population_id NULL =
    project default."""

    __tablename__ = "matching_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    population_id: Mapped[int | None] = mapped_column(ForeignKey("populations.id"))
    name: Mapped[str] = mapped_column(String(128), default="default", nullable=False)

    # possible-match tier
    pi_max: Mapped[float] = mapped_column(Float, default=0.0005, nullable=False)
    pisib_max: Mapped[float] = mapped_column(Float, default=0.01, nullable=False)
    max_ado_mm_match: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    max_1ic_match: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    max_2ic_match: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    max_total_mm_match: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    # reliable-match tier (stricter)
    reliable_pi_max: Mapped[float] = mapped_column(Float, default=0.00001, nullable=False)
    reliable_pisib_max: Mapped[float] = mapped_column(Float, default=0.005, nullable=False)
    reliable_max_ado_mm: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    reliable_max_1ic: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reliable_max_2ic: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reliable_max_total: Mapped[int] = mapped_column(Integer, default=2, nullable=False)

    # Pirog additions / mode toggles
    min_shared_loci: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    mismatch_metric: Mapped[MismatchMetric] = mapped_column(
        SAEnum(MismatchMetric, name="mismatch_metric"),
        default=MismatchMetric.decomposed, nullable=False,
    )
    use_pi_gate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tm_possible: Mapped[int] = mapped_column(Integer, default=4, nullable=False)  # flat Tm
    tm_reliable: Mapped[int] = mapped_column(Integer, default=2, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MatchingRun(Base):
    __tablename__ = "matching_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    population_id: Mapped[int] = mapped_column(
        ForeignKey("populations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    triggered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus, name="run_status"), default=RunStatus.queued, nullable=False
    )
    mode: Mapped[MatchingMode] = mapped_column(
        SAEnum(MatchingMode, name="matching_mode"),
        default=MatchingMode.reference_anchored, nullable=False,
    )
    settings_snapshot: Mapped[dict | None] = mapped_column(JSON)
    incremental: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    single_sample_id: Mapped[int | None] = mapped_column(ForeignKey("samples.id"))
    n_samples: Mapped[int | None] = mapped_column(Integer)
    n_matches: Mapped[int | None] = mapped_column(Integer)
    n_subgroups: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(String(4096))


class MatchSubgroup(Base):
    """One putative individual animal (MisBase subgroup)."""

    __tablename__ = "match_subgroups"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    population_id: Mapped[int] = mapped_column(
        ForeignKey("populations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    run_id: Mapped[int | None] = mapped_column(ForeignKey("matching_runs.id"))
    label: Mapped[str | None] = mapped_column(String(128))  # animal ID
    reference_sample_id: Mapped[int | None] = mapped_column(ForeignKey("samples.id"))
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sex: Mapped[Sex] = mapped_column(SAEnum(Sex, name="sex"), default=Sex.unknown, nullable=False)
    n_samples: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


match_supergroup_members = Table(
    "match_supergroup_members",
    Base.metadata,
    Column("supergroup_id", ForeignKey("match_supergroups.id", ondelete="CASCADE"),
           primary_key=True),
    Column("subgroup_id", ForeignKey("match_subgroups.id", ondelete="CASCADE"), primary_key=True),
)


class MatchSupergroup(Base):
    """QC cluster of subgroups linked by cross-matches (does NOT auto-merge animals)."""

    __tablename__ = "match_supergroups"

    id: Mapped[int] = mapped_column(primary_key=True)
    population_id: Mapped[int] = mapped_column(
        ForeignKey("populations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    run_id: Mapped[int | None] = mapped_column(ForeignKey("matching_runs.id"))
    label: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Match(Base):
    """A pairwise comparison result (sample_a_id < sample_b_id canonically)."""

    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("matching_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    population_id: Mapped[int] = mapped_column(ForeignKey("populations.id"), index=True,
                                               nullable=False)
    sample_a_id: Mapped[int] = mapped_column(ForeignKey("samples.id"), index=True, nullable=False)
    sample_b_id: Mapped[int] = mapped_column(ForeignKey("samples.id"), index=True, nullable=False)
    loci_matched: Mapped[int | None] = mapped_column(Integer)
    loci_compared: Mapped[int | None] = mapped_column(Integer)
    num_ado_mm: Mapped[int | None] = mapped_column(Integer)
    num_1ic: Mapped[int | None] = mapped_column(Integer)
    num_2ic: Mapped[int | None] = mapped_column(Integer)
    num_total_ic: Mapped[int | None] = mapped_column(Integer)
    flat_mismatch: Mapped[int | None] = mapped_column(Integer)
    d_pi: Mapped[float | None] = mapped_column(Float)
    d_pi_sib: Mapped[float | None] = mapped_column(Float)
    tier: Mapped[MatchTier] = mapped_column(
        SAEnum(MatchTier, name="match_tier"), default=MatchTier.none, nullable=False
    )
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("run_id", "sample_a_id", "sample_b_id", name="uq_match_run_pair"),
    )


class MatchingLog(Base):
    __tablename__ = "matching_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("matching_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    seq: Mapped[int | None] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    message: Mapped[str] = mapped_column(String(4096), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
