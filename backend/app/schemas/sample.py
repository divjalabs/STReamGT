from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.enums import Sex, ConsensusSource


class SampleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    public_id: str
    system_code: str
    name: str
    project_id: int
    population_id: int | None
    study_id: int | None
    kit_id: int | None
    sex: Sex
    sex_locked: bool
    genotype_ok: bool
    discard_sample: bool
    quality_index: float | None
    n_replicates: int | None
    subgroup_id: int | None


class ConsensusGenotypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    marker: str
    allele1: str | None
    allele2: str | None
    allele3: str | None
    allele4: str | None
    ncnf_a1: int | None
    ncnf_a2: int | None
    confirmed_alleles: str
    unconfirmed_alleles: str
    n_amp: int | None
    n_amp_ok: int | None
    success_rate: float | None
    ado: int | None
    ado_rate: float | None
    quality_index: float | None
    false_alleles: int | None
    reads_per_amp: int | None
    sd_reads_per_amp: float | None
    n_obs_a1: int | None = None   # replicate observations of allele1 (MisBase N.Al1)
    n_obs_a2: int | None = None   # replicate observations of allele2 (MisBase N.Al2)
    is_locked: bool
    is_edited: bool
    source: ConsensusSource


class SampleDetail(SampleSummary):
    consensus: list[ConsensusGenotypeOut] = []
    kit_code: str | None = None
    animal_label: str | None = None    # MatchSubgroup.label of the assigned animal
    sex_marker: str | None = None      # marker name used for sex determination (e.g. "SRY")


class SampleUpdate(BaseModel):
    """Reassign a sample's population/study and set QC overrides. Setting `sex` locks it."""
    population_id: int | None = None
    study_id: int | None = None
    discard_sample: bool | None = None
    genotype_ok: bool | None = None
    sex: Sex | None = None
    sex_locked: bool | None = None


class ConsensusEdit(BaseModel):
    """Manual allele-call edits (display names); the sequence identity is re-resolved server-side."""
    allele1: str | None = None
    allele2: str | None = None
    allele3: str | None = None
    allele4: str | None = None


class PlotPoint(BaseModel):
    length: int | None
    reads: int | None
    flagged: bool
    stutter: bool = False
    allele_name: str | None


class MarkerPlot(BaseModel):
    marker: str
    title: str
    lines: list[list[list[float]]]      # replicate polylines: [[[length, reads], …], …]
    points: list[PlotPoint]


class ReplicateObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    marker: str
    plate: str | None
    position: int | None
    tag_combo: str | None
    run_name: str | None
    read_count: int | None
    length: int | None
    flag: str
    stutter: bool
    sequence: str | None
    allele_name: str | None
