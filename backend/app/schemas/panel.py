from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict

from app.models.enums import PrimerType


class PrimerIn(BaseModel):
    locus: str
    type: PrimerType
    primer_f: str | None = None
    primer_r: str | None = None
    motif: str | None = None
    sequence: str | None = None


class PrimerOut(PrimerIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class PanelCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    species_common: str | None = None
    species_latin: str | None = None
    description: str | None = None
    primers_csv_key: str | None = None
    primers: list[PrimerIn] = []


class PanelUpdate(BaseModel):
    """Rename / relabel a panel (admin)."""

    code: str | None = None
    species_common: str | None = None
    species_latin: str | None = None
    description: str | None = None


class PanelSummary(BaseModel):
    """Lightweight view for the panel dropdown in the kit form."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    species_common: str | None
    species_latin: str | None
    primer_count: int = 0


class PanelOut(PanelSummary):
    description: str | None
    primers_csv_key: str | None
    primers: list[PrimerOut]


class TagLayoutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    column_names: list[str]
