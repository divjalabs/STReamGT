from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import PrimerType, ControlKind


class Kit(Base):
    """A lab kit: a stable mapping of kit_code -> primers, tag columns, controls, species.

    Admin-curated. Users pick a kit at submission time and its primers/tags/controls
    are attached to the generated input.tsv rows.
    """

    __tablename__ = "kits"

    id: Mapped[int] = mapped_column(primary_key=True)
    kit_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    species: Mapped[str | None] = mapped_column(String(64))       # e.g. wolf / lynx / bear
    description: Mapped[str | None] = mapped_column(String(1024))
    # Canonical CSVs stored in S3 (the pipeline needs the actual files at run time).
    primers_csv_key: Mapped[str | None] = mapped_column(String(512))
    tags_csv_key: Mapped[str | None] = mapped_column(String(512))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    primers: Mapped[list["Primer"]] = relationship(
        back_populates="kit", cascade="all, delete-orphan"
    )
    tag_columns: Mapped[list["TagColumn"]] = relationship(
        back_populates="kit", cascade="all, delete-orphan", order_by="TagColumn.ordinal"
    )
    controls: Mapped[list["Control"]] = relationship(
        back_populates="kit", cascade="all, delete-orphan"
    )


class Primer(Base):
    """One locus row of the kit's primers CSV (e.g. UA_primers.csv)."""

    __tablename__ = "primers"

    id: Mapped[int] = mapped_column(primary_key=True)
    kit_id: Mapped[int] = mapped_column(ForeignKey("kits.id"), index=True, nullable=False)
    locus: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[PrimerType] = mapped_column(SAEnum(PrimerType, name="primer_type"), nullable=False)
    primer_f: Mapped[str | None] = mapped_column(String(512))
    primer_r: Mapped[str | None] = mapped_column(String(512))
    motif: Mapped[str | None] = mapped_column(String(128))
    sequence: Mapped[str | None] = mapped_column(String(2048))

    kit: Mapped["Kit"] = relationship(back_populates="primers")


class TagColumn(Base):
    """A PP column (PP1..PP8) available in the kit's tags CSV header.

    The user selects a subset of these per sample batch (e.g. PP1-PP4).
    """

    __tablename__ = "tag_columns"

    id: Mapped[int] = mapped_column(primary_key=True)
    kit_id: Mapped[int] = mapped_column(ForeignKey("kits.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(16), nullable=False)   # "PP1".."PP8"
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)   # 1..8, for ordering/ranges

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
