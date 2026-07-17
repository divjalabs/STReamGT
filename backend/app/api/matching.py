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
    User, Population, MatchingRun, MatchSubgroup, MatchSupergroup, match_supergroup_members, Match,
)
from app.schemas.matching import (
    MatchingRunOut, MatchSubgroupOut, MatchOut, MatchingSettingsOut, MatchingSettingsUpdate,
    SupergroupOut,
)
from app.services.matching.runner import run_matching, get_or_create_settings

router = APIRouter(tags=["matching"])


def _population(db: Session, population_id: int, current: User, *, need_edit=False) -> Population:
    pop = db.get(Population, population_id)
    if pop is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Population not found")
    get_accessible_project(pop.project_id, need_edit=need_edit, db=db, user=current)
    return pop


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
    return db.scalars(
        select(MatchSubgroup).where(MatchSubgroup.population_id == population_id)
        .order_by(MatchSubgroup.n_samples.desc(), MatchSubgroup.id)
    ).all()


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
