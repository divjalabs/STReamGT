"""Project tenancy: Project -> Population -> Study -> Samples -> Animals.

A Project is the container that owns samples, animals, and matching. It aggregates samples
produced by many jobs/kits, so project access is DECOUPLED from kit_access: kit_access still
gates job submission, while project_access (below) gates the animal/sample/consensus/matching
data. Matching runs per Population.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    String, Integer, Boolean, DateTime, ForeignKey, Enum as SAEnum, Table, Column,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import ProjectRole


# --- many-to-many: which users (beyond the owner) can see/edit a project ---
project_access = Table(
    "project_access",
    Base.metadata,
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role", SAEnum(ProjectRole, name="project_role"), default=ProjectRole.viewer,
           nullable=False),
)


# --- many-to-many: kits attached to a study (organisational + drives job ingestion target) ---
study_kits = Table(
    "study_kits",
    Base.metadata,
    Column("study_id", ForeignKey("studies.id", ondelete="CASCADE"), primary_key=True),
    Column("kit_id", ForeignKey("kits.id", ondelete="CASCADE"), primary_key=True),
)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    organisation: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(2048))
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("owner_user_id", "name", name="uq_project_owner_name"),)

    owner: Mapped["User"] = relationship()  # noqa: F821
    shared_users: Mapped[list["User"]] = relationship(secondary=project_access)  # noqa: F821
    populations: Mapped[list["Population"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    studies: Mapped[list["Study"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Population(Base):
    """A population within a project (e.g. Dinaric wolf). Matching runs at this level."""

    __tablename__ = "populations"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_population_project_name"),)

    project: Mapped["Project"] = relationship(back_populates="populations")


class Study(Base):
    """A study/sampling campaign within a project. `include_in_matching` mirrors
    tblStudies.IncludeInMatching."""

    __tablename__ = "studies"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    population_id: Mapped[int | None] = mapped_column(ForeignKey("populations.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    include_in_matching: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_study_project_name"),)

    project: Mapped["Project"] = relationship(back_populates="studies")
    # Kits attached to this study; a job on an attached kit ingests into this study.
    kits: Mapped[list["Kit"]] = relationship(secondary=study_kits)  # noqa: F821


class SampleType(Base):
    """Sample-type catalog (mirrors tblSampleTypes). project_id NULL = global default."""

    __tablename__ = "sample_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    exclude_from_analysis: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reliable_sample_type: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_sampletype_project_code"),)
