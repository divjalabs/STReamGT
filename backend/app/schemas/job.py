from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict, model_validator

from app.models.enums import JobStatus, FastqSource, ResultKind


# ---------- uploads ----------

class UploadInitRequest(BaseModel):
    filename: str
    size: int = Field(ge=0)
    content_type: str = "application/octet-stream"
    purpose: str = Field(default="fastq", pattern="^(fastq|sample)$")


class UploadInitResponse(BaseModel):
    key: str
    method: str                       # "multipart" | "put"
    put_url: str | None = None        # when method == "put"
    upload_id: str | None = None      # when method == "multipart"
    part_size: int | None = None
    part_urls: list[str] | None = None


class UploadedPart(BaseModel):
    part_number: int = Field(ge=1)
    etag: str


class MultipartCompleteRequest(BaseModel):
    key: str
    upload_id: str
    parts: list[UploadedPart]


# ---------- job creation ----------

class SampleBatchIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    sample_sheet_key: str | None = None       # uploaded .xlsx S3 key
    sample_names_text: str | None = None      # pasted names/positions
    species: str | None = None
    selected_tags: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _need_samples(self):
        if not self.sample_sheet_key and not self.sample_names_text:
            raise ValueError("each batch needs either sample_sheet_key or sample_names_text")
        return self


class JobCreate(BaseModel):
    kit_id: int
    fastq_source: FastqSource = FastqSource.upload
    fastq1_ref: str
    fastq2_ref: str
    min_identity: float = 0.9
    min_overlap: int = 20
    expected_read_number: int | None = None
    batches: list[SampleBatchIn] = Field(min_length=1)


# ---------- job output ----------

class SampleBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    species: str | None
    selected_tags: list[str]
    sample_sheet_key: str | None


class ResultFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: ResultKind
    filename: str
    size_bytes: int | None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    public_id: str
    status: JobStatus
    kit_id: int
    fastq_source: FastqSource
    min_identity: float
    min_overlap: int
    expected_read_number: int | None
    observed_read_count: int | None
    reads_confirmed: bool
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    batches: list[SampleBatchOut]
    result_files: list[ResultFileOut]


class JobConfirm(BaseModel):
    """Answer to an awaiting_confirmation job: run it anyway, or cancel."""
    proceed: bool = True


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    public_id: str
    status: JobStatus
    kit_id: int
    created_at: datetime
    finished_at: datetime | None


class ResultDownload(BaseModel):
    kind: ResultKind
    filename: str
    url: str
