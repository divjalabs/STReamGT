"""Matching API: run matching for a population, read animals (subgroups) + matches, and manage
the threshold settings. Runs inline (fast at per-population scale)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.auth.deps import get_current_user
from app.auth.access import get_accessible_project
from app.models import (
    User, Population, Sample, MatchingRun, MatchSubgroup, MatchSupergroup, match_supergroup_members,
    Match, AnimalOverride,
)
from app.schemas.matching import (
    MatchingRunOut, MatchSubgroupOut, MatchOut, MatchingSettingsOut, MatchingSettingsUpdate,
    SupergroupOut, AnimalDetailOut, AnimalMemberOut, AnimalUpdate,
)
from app.services.matching.runner import run_matching, get_or_create_settings
from app.services.matching import single

router = APIRouter(tags=["matching"])


def _population(db: Session, population_id: int, current: User, *, need_edit=False) -> Population:
    pop = db.get(Population, population_id)
    if pop is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Population not found")
    get_accessible_project(pop.project_id, need_edit=need_edit, db=db, user=current)
    return pop


def _subgroup(db: Session, subgroup_id: int, current: User, *, need_edit=False) -> MatchSubgroup:
    sg = db.get(MatchSubgroup, subgroup_id)
    if sg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Animal not found")
    pop = db.get(Population, sg.population_id)
    get_accessible_project(pop.project_id, need_edit=need_edit, db=db, user=current)
    return sg


def _override_of(db: Session, sg: MatchSubgroup) -> AnimalOverride | None:
    if sg.reference_sample_id is None:
        return None
    return db.scalar(select(AnimalOverride).where(
        AnimalOverride.reference_sample_id == sg.reference_sample_id))


def _animal_detail(db: Session, sg: MatchSubgroup) -> AnimalDetailOut:
    ov = _override_of(db, sg)
    members = db.scalars(
        select(Sample).where(Sample.subgroup_id == sg.id).order_by(Sample.system_code)).all()
    ref_code = None
    if sg.reference_sample_id is not None:
        rs = db.get(Sample, sg.reference_sample_id)
        ref_code = rs.system_code if rs else None
    return AnimalDetailOut(
        id=sg.id, public_id=sg.public_id, label=sg.label, population_id=sg.population_id,
        reference_sample_id=sg.reference_sample_id, reference_system_code=ref_code,
        n_samples=len(members), n_reliable=single.reliable_count(db, sg),
        reliably_genotyped=(ov.reliably_genotyped if ov else False),
        is_confirmed=(ov.is_confirmed if ov else sg.is_confirmed),
        sex=sg.sex,
        members=[AnimalMemberOut(id=m.id, system_code=m.system_code, name=m.name,
                                 is_reference=(m.id == sg.reference_sample_id)) for m in members],
    )


@router.post("/populations/{population_id}/rerun-match", response_model=MatchingRunOut)
def rerun_match(
    population_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    _population(db, population_id, current, need_edit=True)
    run = run_matching(db, population_id, user_id=current.id)
    db.commit()
    db.refresh(run)
    return run


@router.get("/matching-runs/{public_id}", response_model=MatchingRunOut)
def get_run(public_id: str, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    run = db.scalar(select(MatchingRun).where(MatchingRun.public_id == public_id))
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    pop = db.get(Population, run.population_id)
    get_accessible_project(pop.project_id, db=db, user=current)
    return run


@router.get("/populations/{population_id}/subgroups", response_model=list[MatchSubgroupOut])
def list_subgroups(
    population_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    _population(db, population_id, current)
    subs = db.scalars(
        select(MatchSubgroup).where(MatchSubgroup.population_id == population_id)
        .order_by(MatchSubgroup.n_samples.desc(), MatchSubgroup.id)
    ).all()
    rg = dict(db.execute(
        select(AnimalOverride.reference_sample_id, AnimalOverride.reliably_genotyped)
        .where(AnimalOverride.population_id == population_id)
    ).all())
    for sg in subs:
        sg.reliably_genotyped = rg.get(sg.reference_sample_id, False)   # transient attr
    return subs


@router.get("/subgroups/{subgroup_id}", response_model=AnimalDetailOut)
def get_subgroup(
    subgroup_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    sg = _subgroup(db, subgroup_id, current)
    detail = _animal_detail(db, sg)
    db.commit()          # get_or_create_settings (in reliable_count) may have created a default row
    return detail


@router.post("/subgroups/{subgroup_id}/rematch")
def rematch_subgroup(
    subgroup_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    """Re-match this animal's reference against the population; returns candidate matches + the
    per-locus genotype grid (display-only, persists nothing)."""
    sg = _subgroup(db, subgroup_id, current)
    result = single.rematch_reference(db, sg)
    db.commit()
    return result


@router.patch("/subgroups/{subgroup_id}", response_model=AnimalDetailOut)
def update_subgroup(
    subgroup_id: int, payload: AnimalUpdate,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    sg = _subgroup(db, subgroup_id, current, need_edit=True)
    data = payload.model_dump(exclude_unset=True)

    # Change the reference sample: pin it (survives full reruns), relabel, carry the override over.
    new_ref = data.get("reference_sample_id")
    if new_ref is not None and new_ref != sg.reference_sample_id:
        target = db.get(Sample, new_ref)
        if target is None or target.subgroup_id != sg.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "reference must be a member of this animal")
        old_ref = sg.reference_sample_id
        if old_ref is not None:
            old = db.get(Sample, old_ref)
            if old is not None:
                old.is_animal_reference = False
            moved = db.scalar(select(AnimalOverride).where(
                AnimalOverride.reference_sample_id == old_ref))
            if moved is not None:
                moved.reference_sample_id = new_ref
        target.is_animal_reference = True
        sg.reference_sample_id = new_ref
        sg.label = target.system_code

    # Upsert the persistent per-animal flags (keyed by the current reference sample).
    flags = {k: data[k] for k in ("reliably_genotyped", "is_confirmed", "notes") if k in data}
    if flags:
        ov = _override_of(db, sg)
        if ov is None:
            ov = AnimalOverride(population_id=sg.population_id,
                                reference_sample_id=sg.reference_sample_id)
            db.add(ov)
        for k, v in flags.items():
            setattr(ov, k, v)
        if "is_confirmed" in flags:
            sg.is_confirmed = flags["is_confirmed"]

    db.commit()
    db.refresh(sg)
    detail = _animal_detail(db, sg)
    db.commit()
    return detail


@router.get("/populations/{population_id}/supergroups", response_model=list[SupergroupOut])
def list_supergroups(
    population_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    _population(db, population_id, current)
    out = []
    for s in db.scalars(
        select(MatchSupergroup).where(MatchSupergroup.population_id == population_id)):
        ids = list(db.scalars(select(match_supergroup_members.c.subgroup_id)
                              .where(match_supergroup_members.c.supergroup_id == s.id)))
        out.append(SupergroupOut(id=s.id, label=s.label, subgroup_ids=ids))
    return out


@router.get("/populations/{population_id}/matches", response_model=list[MatchOut])
def list_matches(
    population_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    _population(db, population_id, current)
    return db.scalars(
        select(Match).where(Match.population_id == population_id)
        .order_by(Match.tier.desc(), Match.num_total_ic)
    ).all()


@router.get("/populations/{population_id}/matching-settings", response_model=MatchingSettingsOut)
def get_settings(
    population_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    pop = _population(db, population_id, current)
    settings = get_or_create_settings(db, pop.project_id, population_id)
    db.commit()
    return settings


@router.put("/populations/{population_id}/matching-settings", response_model=MatchingSettingsOut)
def update_settings(
    population_id: int, payload: MatchingSettingsUpdate,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    pop = _population(db, population_id, current, need_edit=True)
    settings = get_or_create_settings(db, pop.project_id, population_id)
    # Write the override at the population level (don't mutate a shared project default).
    if settings.population_id is None:
        from app.models import MatchingSettings
        settings = MatchingSettings(project_id=pop.project_id, population_id=population_id,
                                    name="population")
        db.add(settings)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(settings, k, v)
    db.commit()
    db.refresh(settings)
    return settings
