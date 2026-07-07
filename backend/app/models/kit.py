from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    String, Integer, DateTime, ForeignKey, Enum as SAEnum, Table, Column, JSON, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import PrimerType, ControlKind, KitStatus


# --- many-to-many: which users can see/use a kit (non-admins) ---
kit_access = Table(
    "kit_access",
    Base.metadata,
    Column("kit_id", ForeignKey("kits.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class PrimerPanel(Base):
    """A reusable primer panel (per species/multiplex), e.g. UA (brown bear), LL_MPA (lynx).

    Seeded from STReam_primers_tags/. Admins pick a panel when registering a kit; its primers
    CSV (in S3) is what the pipeline actually uses.
    """

    __tablename__ = "primer_panels"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    species_common: Mapped[str | None] = mapped_column(String(128))  # "brown bear"
    species_latin: Mapped[str | None] = mapped_column(String(128))   # "Ursus arctos"
    description: Mapped[str | None] = mapped_column(String(1024))
    primers_csv_key: Mapped[str | None] = mapped_column(String(512))  # canonical CSV in S3
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    primers: Mapped[list["Primer"]] = relationship(
        back_populates="panel", cascade="all, delete-orphan"
    )

    @property
    def primer_count(self) -> int:
        return len(self.primers)


class Primer(Base):
    """One locus row of a panel's primers CSV (belongs to a PrimerPanel, not a kit)."""

    __tablename__ = "primers"

    id: Mapped[int] = mapped_column(primary_key=True)
    panel_id: Mapped[int] = mapped_column(
        ForeignKey("primer_panels.id"), index=True, nullable=False
    )
    locus: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[PrimerType] = mapped_column(SAEnum(PrimerType, name="primer_type"), nullable=False)
    primer_f: Mapped[str | None] = mapped_column(String(512))
    primer_r: Mapped[str | None] = mapped_column(String(512))
    motif: Mapped[str | None] = mapped_column(String(128))
    sequence: Mapped[str | None] = mapped_column(String(2048))

    panel: Mapped["PrimerPanel"] = relationship(back_populates="primers")


class TagLayout(Base):
    """The shared tag layout (one row): the tags CSV + the PP columns available to pick from.

    Same for all kits (e.g. PP1..PP12). Seeded from STReam_primers_tags/tags.csv.
    """

    __tablename__ = "tag_layouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    tags_csv_key: Mapped[str | None] = mapped_column(String(512))  # canonical CSV in S3
    column_names: Mapped[list[str]] = mapped_column(  # ["PP1", ... "PP12"]
        JSON, default=list, nullable=False
    )


class Kit(Base):
    """A lab kit assigned to client(s): a chosen primer panel + a selected subset of tag columns.

    Denormalizes primers_csv_key / tags_csv_key / species from the panel + layout on save, so the
    worker and submit page stay unchanged. Access is controlled per-user via kit_access.
    """

    __tablename__ = "kits"

    id: Mapped[int] = mapped_column(primary_key=True)
    kit_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    panel_id: Mapped[int | None] = mapped_column(ForeignKey("primer_panels.id"))
    species: Mapped[str | None] = mapped_column(String(128))       # denormalized from the panel
    description: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[KitStatus] = mapped_column(
        SAEnum(KitStatus, name="kit_status"), default=KitStatus.sent, nullable=False
    )
    # Canonical CSVs the pipeline reads at run time (denormalized from panel + layout).
    primers_csv_key: Mapped[str | None] = mapped_column(String(512))
    tags_csv_key: Mapped[str | None] = mapped_column(String(512))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    panel: Mapped["PrimerPanel"] = relationship()
    tag_columns: Mapped[list["TagColumn"]] = relationship(
        back_populates="kit", cascade="all, delete-orphan", order_by="TagColumn.ordinal"
    )
    controls: Mapped[list["Control"]] = relationship(
        back_populates="kit", cascade="all, delete-orphan"
    )
    # Users granted access to this kit (non-admins). Admins see all kits regardless.
    users: Mapped[list["User"]] = relationship(secondary=kit_access)  # noqa: F821

    @property
    def assigned_user_ids(self) -> list[int]:
        return [u.id for u in self.users]


class TagColumn(Base):
    """A PP column selected for a kit (subset of the shared TagLayout).

    The user picks a further subset of these per sample batch (e.g. PP1-PP4).
    """

    __tablename__ = "tag_columns"

    id: Mapped[int] = mapped_column(primary_key=True)
    kit_id: Mapped[int] = mapped_column(ForeignKey("kits.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(16), nullable=False)   # "PP1".."PP12"
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)   # numeric suffix, for ranges

    kit: Mapped["Kit"] = relationship(back_populates="tag_columns")


class Control(Base):
    """Name pattern identifying a control sample (maps to parameters.json negative_name)."""

    __tablename__ = "controls"

    id: Mapped[int] = mapped_column(primary_key=True)
    kit_id: Mapped[int] = mapped_column(ForeignKey("kits.id"), index=True, nullable=False)
    name_pattern: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. "blank"
    kind: Mapped[ControlKind] = mapped_column(
        SAEnum(ControlKind, name="control_kind"), default=ControlKind.negative, nullable=False
    )

    kit: Mapped["Kit"] = relationship(back_populates="controls")
