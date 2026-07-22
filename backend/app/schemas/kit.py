from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict

from app.models.enums import ControlKind, KitStatus
from app.schemas.panel import PanelSummary


class TagColumnIn(BaseModel):
    name: str = Field(examples=["PP1"])
    ordinal: int = Field(ge=1)


class ControlIn(BaseModel):
    name_pattern: str = Field(examples=["blank"])
    kind: ControlKind = ControlKind.negative


class TagColumnOut(TagColumnIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ControlOut(ControlIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


def _default_controls() -> list[ControlIn]:
    return [ControlIn(name_pattern="blank", kind=ControlKind.negative)]


class KitCreate(BaseModel):
    """Admin registers a kit by picking a panel + tag columns (no file uploads)."""

    kit_code: str = Field(min_length=1, max_length=64)
    panel_id: int
    selected_tags: list[str] = Field(min_length=1, examples=[["PP1", "PP2", "PP3", "PP4"]])
    controls: list[ControlIn] = Field(default_factory=_default_controls)
    description: str | None = None
    status: KitStatus = KitStatus.sent
    assigned_user_ids: list[int] = []


class KitUpdate(BaseModel):
    """Admin edits status/description/access; a client may only set status=received on their kit."""

    status: KitStatus | None = None
    description: str | None = None
    assigned_user_ids: list[int] | None = None


class KitStudyRef(BaseModel):
    """A study this kit is attached to — lets the Submit page pre-fill the ingestion target."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    project_id: int
    population_id: int | None


class KitSummary(BaseModel):
    """Lightweight view for the kit picker / client kit list / admin table."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    kit_code: str
    species: str | None
    status: KitStatus
    updated_at: datetime | None = None   # last status change; None on older rows pre-migration
    tag_columns: list[TagColumnOut]
    assigned_user_ids: list[int]
    studies: list[KitStudyRef] = []      # studies this kit is attached to (transient; see api/kits)


class KitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kit_code: str
    species: str | None
    description: str | None
    status: KitStatus
    panel: PanelSummary | None
    tag_columns: list[TagColumnOut]
    controls: list[ControlOut]
    assigned_user_ids: list[int]
