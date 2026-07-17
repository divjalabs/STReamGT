from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import RunStatus, MatchTier, MismatchMetric


class MatchingRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    public_id: str
    status: RunStatus
    n_samples: int | None
    n_matches: int | None
    n_subgroups: int | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None


class MatchSubgroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    public_id: str
    label: str | None
    reference_sample_id: int | None
    n_samples: int | None
    is_confirmed: bool


class SupergroupOut(BaseModel):
    id: int
    label: str | None
    subgroup_ids: list[int]      # the animals (subgroups) this QC cluster links


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    sample_a_id: int
    sample_b_id: int
    loci_matched: int | None
    num_ado_mm: int | None
    num_1ic: int | None
    num_2ic: int | None
    flat_mismatch: int | None
    d_pi: float | None
    tier: MatchTier


class MatchingSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    min_shared_loci: int
    mismatch_metric: MismatchMetric
    use_pi_gate: bool
    tm_possible: int
    tm_reliable: int
    max_ado_mm_match: int
    max_1ic_match: int
    max_2ic_match: int
    max_total_mm_match: int
    reliable_max_ado_mm: int
    reliable_max_1ic: int
    reliable_max_2ic: int
    reliable_max_total: int
    pi_max: float
    pisib_max: float
    reliable_pi_max: float
    reliable_pisib_max: float


class MatchingSettingsUpdate(BaseModel):
    min_shared_loci: int | None = None
    mismatch_metric: MismatchMetric | None = None
    use_pi_gate: bool | None = None
    tm_possible: int | None = None
    tm_reliable: int | None = None
    max_ado_mm_match: int | None = None
    max_1ic_match: int | None = None
    max_2ic_match: int | None = None
    max_total_mm_match: int | None = None
    reliable_max_ado_mm: int | None = None
    reliable_max_1ic: int | None = None
    reliable_max_2ic: int | None = None
    reliable_max_total: int | None = None
    pi_max: float | None = None
    pisib_max: float | None = None
    reliable_pi_max: float | None = None
    reliable_pisib_max: float | None = None
