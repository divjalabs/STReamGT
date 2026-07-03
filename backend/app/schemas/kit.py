from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict

from app.models.enums import PrimerType, ControlKind


class PrimerIn(BaseModel):
    locus: str
    type: PrimerType
    primer_f: str | None = None
    primer_r: str | None = None
    motif: str | None = None
    sequence: str | None = None


class TagColumnIn(BaseModel):
    name: str = Field(examples=["PP1"])
    ordinal: int = Field(ge=1)


class ControlIn(BaseModel):
    name_pattern: str = Field(examples=["blank"])
    kind: ControlKind = ControlKind.negative


class KitCreate(BaseModel):
    kit_code: str = Field(min_length=1, max_length=64)
    species: str | None = None
    description: str | None = None
    primers_csv_key: str | None = None
    tags_csv_key: str | None = None
    primers: list[PrimerIn] = []
    tag_columns: list[TagColumnIn] = []
    controls: list[ControlIn] = []


class PrimerOut(PrimerIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class TagColumnOut(TagColumnIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ControlOut(ControlIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class KitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kit_code: str
    species: str | None
    description: str | None
    primers_csv_key: str | None
    tags_csv_key: str | None
    primers: list[PrimerOut]
    tag_columns: list[TagColumnOut]
    controls: list[ControlOut]


class KitSummary(BaseModel):
    """Lightweight view for the kit picker on the submit page."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kit_code: str
    species: str | None
    tag_columns: list[TagColumnOut]
