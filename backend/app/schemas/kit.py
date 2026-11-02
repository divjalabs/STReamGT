from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict

from app.models.enums import ControlKind, KitStatus
from app.schemas.panel import PanelSummary


class TagColumnIn(BaseModel):
    name: str = Field(examples=["PP1"])
    ordinal: int = Field(ge=1)


class ControlIn(BaseModel):
    kind: ControlKind = ControlKind.sequencing
    name_pattern: str | None = None          # legacy substring; set for pattern-based controls
    position: str | None = Field(default=None, examples=["A1"])  # plate well for position controls
    name: str | None = None                  # explicit name; auto-generated if blank


class TagColumnOut(TagColumnIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ControlOut(ControlIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


def _default_controls() -> list[ControlIn]:
    return [ControlIn(name_pattern="blank", kind=ControlKind.sequencing)]


class ControlTemplateIn(BaseModel):
    """A reusable plate control layout — kind + well (+ optional name) per control."""
    name: str = Field(min_length=1, max_length=128)
    positions: list[ControlIn] = Field(default_factory=list)


class ControlTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    positions: list[dict] = []


class KitCreate(BaseModel):
    """Admin registers a kit by picking a panel + tag columns (no file uploads)."""

    kit_code: str = Field(min_length=1, max_length=64)
    panel_id: int
    selected_tags: list[str] = Field(min_length=1, examples=[["PP1", "PP2", "PP3", "PP4"]])
    controls: list[ControlIn] = Field(default_factory=_default_controls)
    description: str | None = None
    status: KitStatus = KitStatus.sent


class KitBatchCreate(BaseModel):
    """Register several kits at once; the server names them `<panel>_<YYMMDD>_<NN>`.

    Everything except `count` is shared by the whole batch — which is how the register form has
    always worked, one kit at a time.
    """

    panel_id: int
    count: int = Field(ge=1, le=200, description="how many kits to register")
    selected_tags: list[str] = Field(min_length=1, examples=[["PP1", "PP2", "PP3", "PP4"]])
    controls: list[ControlIn] = Field(default_factory=_default_controls)
    description: str | None = None
    status: KitStatus = KitStatus.sent


class KitStickerRow(BaseModel):
    """One printed sticker: what identifies the kit, and the code the lab redeems."""

    kit_code: str
    claim_code: str
    species: str | None = None
    panel: str | None = None
    registered: str | None = None


class KitBatchOut(BaseModel):
    """The batch, with each kit's claim code — the response the sticker sheet is built from."""

    kits: list[KitStickerRow]
    panel: str
    species: str | None = None
    registered: str


class KitStickerSheetRequest(BaseModel):
    """Rows to format as .xlsx: exactly one registration's kits, echoed back from the response."""

    rows: list[KitStickerRow] = Field(min_length=1, max_length=500)


class KitUpdate(BaseModel):
    """Admin edits status/description/access; a client may only set status=received on their kit."""

    status: KitStatus | None = None
    description: str | None = None
    assigned_user_ids: list[int] | None = None


class KitReadsIn(BaseModel):
    """Register/replace a kit's server-side FASTQ pair (keys already uploaded to S3)."""
    fastq1_key: str
    fastq2_key: str
    fastq1_name: str | None = None
    fastq2_name: str | None = None
    size1: int | None = None
    size2: int | None = None


class KitReadsBrief(BaseModel):
    """Compact reads status for the My kits list."""
    model_config = ConfigDict(from_attributes=True)
    fastq1_name: str | None
    fastq2_name: str | None
    uploaded_at: datetime


class KitReadsOut(KitReadsBrief):
    fastq1_key: str
    fastq2_key: str
    size1: int | None = None
    size2: int | None = None
    uploaded_by_email: str | None = None


class ReadDownload(BaseModel):
    """One half of a kit's FASTQ pair, with a presigned link the browser fetches directly."""

    filename: str
    url: str                 # attachment disposition; expires per settings.presign_expire_seconds
    size_bytes: int | None = None


class KitSetupBatch(BaseModel):
    """A sample batch as drafted. Same shape as SampleBatchIn, minus its completeness rules."""

    name: str | None = None
    selected_tags: list[str] = []
    sample_names_text: str | None = None


class KitSetupIn(BaseModel):
    """The whole sheet — every field is replaced on save, so send all of it."""

    project_id: int | None = None
    default_population_id: int | None = None
    default_study_id: int | None = None
    expected_read_number: int | None = None
    parameters: dict | None = None
    batches: list[KitSetupBatch] = Field(default_factory=list, max_length=20)


class KitSetupOut(KitSetupIn):
    model_config = ConfigDict(from_attributes=True)

    updated_at: datetime
    updated_by_email: str | None = None


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
    description: str | None = None       # shown in the admin table, so a lost one is visible
    status: KitStatus
    updated_at: datetime | None = None   # last status change; None on older rows pre-migration
    tag_columns: list[TagColumnOut]
    controls: list[ControlOut] = []      # control layout (positions/types) for the submit plate
    reads: KitReadsBrief | None = None   # current server-side FASTQ pair, if any
    claimed_by_email: str | None = None  # who redeemed this kit's code (None = unclaimed); admin view
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
    claimed_by_email: str | None = None
    claim_code: str | None = None        # plaintext, returned ONLY on create/regenerate


class ClaimRequest(BaseModel):
    code: str = Field(min_length=1)
