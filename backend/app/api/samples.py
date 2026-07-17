"""Read-only sample + consensus views (M1). Editing / recompute / matching land in M2-M3."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db import get_db
from app.auth.deps import get_current_user
from app.auth.access import get_accessible_project
from app.models import (
    User, Population, Study, Sample, ConsensusGenotype, ReplicateObservation, Kit, MatchSubgroup,
)
from app.schemas.sample import (
    SampleSummary, SampleDetail, ConsensusGenotypeOut, ReplicateObservationOut, SampleUpdate,
    MarkerPlot,
)
from app.schemas.project import PopulationOut
from app.services.plot_data import sample_plot_data
from app.services.qc import SEX_MARKER

router = APIRouter(tags=["samples"])


@router.get("/populations/{population_id}", response_model=PopulationOut)
def get_population(
    population_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    pop = db.get(Population, population_id)
    if pop is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Population not found")
    get_accessible_project(pop.project_id, db=db, user=current)
    return pop


@router.get("/populations/{population_id}/samples", response_model=list[SampleSummary])
def list_population_samples(
    population_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    pop = db.get(Population, population_id)
    if pop is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Population not found")
    get_accessible_project(pop.project_id, db=db, user=current)
    return db.scalars(
        select(Sample).where(Sample.population_id == population_id).order_by(Sample.system_code)
    ).all()


@router.get("/projects/{project_id}/samples", response_model=list[SampleSummary])
def list_project_samples(
    project_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    """All samples in a project (the 'all' navigation set on the sample page)."""
    get_accessible_project(project_id, db=db, user=current)
    return db.scalars(
        select(Sample).where(Sample.project_id == project_id).order_by(Sample.system_code)
    ).all()


@router.get("/samples/{sample_id}", response_model=SampleDetail)
def get_sample(
    sample_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    sample = db.get(Sample, sample_id)
    if sample is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sample not found")
    get_accessible_project(sample.project_id, db=db, user=current)
    consensus = db.scalars(
        select(ConsensusGenotype)
        .where(ConsensusGenotype.sample_id == sample_id)
        .order_by(ConsensusGenotype.marker)
    ).all()
    # replicate observation counts per (marker, allele name) → MisBase N.Al1 / N.Al2
    obs_counts: dict[tuple[str, str], int] = {}
    for marker, allele_name, n in db.execute(
        select(ReplicateObservation.marker, ReplicateObservation.allele_name, func.count())
        .where(ReplicateObservation.sample_id == sample_id,
               ReplicateObservation.called.is_(True),
               ReplicateObservation.allele_name.is_not(None))
        .group_by(ReplicateObservation.marker, ReplicateObservation.allele_name)
    ).all():
        obs_counts[(marker, allele_name)] = n

    detail = SampleDetail.model_validate(sample)
    rows = []
    for c in consensus:
        row = ConsensusGenotypeOut.model_validate(c)
        row.n_obs_a1 = obs_counts.get((c.marker, c.allele1)) if c.allele1 else None
        row.n_obs_a2 = obs_counts.get((c.marker, c.allele2)) if c.allele2 else None
        rows.append(row)
    detail.consensus = rows
    detail.sex_marker = SEX_MARKER
    if sample.kit_id is not None:
        kit = db.get(Kit, sample.kit_id)
        detail.kit_code = kit.kit_code if kit else None
    if sample.subgroup_id is not None:
        sg = db.get(MatchSubgroup, sample.subgroup_id)
        if sg is not None:
            detail.animal_label = sg.label or sg.public_id
    return detail


@router.patch("/samples/{sample_id}", response_model=SampleSummary)
def update_sample(
    sample_id: int, payload: SampleUpdate,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    """Reassign a sample to a different population / study within its project."""
    sample = db.get(Sample, sample_id)
    if sample is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sample not found")
    get_accessible_project(sample.project_id, need_edit=True, db=db, user=current)
    data = payload.model_dump(exclude_unset=True)
    if data.get("population_id") is not None:
        pop = db.get(Population, data["population_id"])
        if pop is None or pop.project_id != sample.project_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "population is not in this sample's project")
    if data.get("study_id") is not None:
        st = db.get(Study, data["study_id"])
        if st is None or st.project_id != sample.project_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "study is not in this sample's project")
    if "sex" in data:                 # a manual sex call locks it against auto-determination
        data.setdefault("sex_locked", True)
    if "population_id" in data and data["population_id"] != sample.population_id:
        sample.subgroup_id = None     # animal assignment is population-scoped; moving invalidates it
    for k, v in data.items():
        setattr(sample, k, v)
    db.commit()
    db.refresh(sample)
    return sample


@router.get("/samples/{sample_id}/replicates", response_model=list[ReplicateObservationOut])
def get_sample_replicates(
    sample_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    sample = db.get(Sample, sample_id)
    if sample is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sample not found")
    get_accessible_project(sample.project_id, db=db, user=current)
    return db.scalars(
        select(ReplicateObservation)
        .where(ReplicateObservation.sample_id == sample_id)
        .order_by(ReplicateObservation.marker, ReplicateObservation.plate,
                  ReplicateObservation.read_count.desc())
    ).all()


@router.get("/samples/{sample_id}/plot-data", response_model=list[MarkerPlot])
def get_sample_plot_data(
    sample_id: int, markers: str | None = None,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    """Consensus genotype plot data (rendered client-side). `markers` = comma-separated filter."""
    sample = db.get(Sample, sample_id)
    if sample is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sample not found")
    get_accessible_project(sample.project_id, db=db, user=current)
    marker_list = [m.strip() for m in markers.split(",") if m.strip()] if markers else None
    return sample_plot_data(db, sample_id, marker_list)


@router.get("/studies/{study_id}/samples", response_model=list[SampleSummary])
def list_study_samples(
    study_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Study not found")
    get_accessible_project(study.project_id, db=db, user=current)
    return db.scalars(
        select(Sample).where(Sample.study_id == study_id).order_by(Sample.system_code)
    ).all()


@router.get("/kits/{kit_id}/samples", response_model=list[SampleSummary])
def list_kit_samples(
    kit_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    """Samples produced by a kit — filtered to those in projects the user can access (a kit can
    feed more than one project)."""
    samples = db.scalars(
        select(Sample).where(Sample.kit_id == kit_id).order_by(Sample.system_code)
    ).all()
    allowed: dict[int, bool] = {}
    out = []
    for s in samples:
        if s.project_id not in allowed:
            try:
                get_accessible_project(s.project_id, db=db, user=current)
                allowed[s.project_id] = True
            except HTTPException:
                allowed[s.project_id] = False
        if allowed[s.project_id]:
            out.append(s)
    return out
