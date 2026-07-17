"""Consensus mutations: recompute from replicates, edit allele calls, lock/unlock.

Recompute + edit run inline (fast, pure-Python over DB rows). All require project edit access.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.auth.deps import get_current_user
from app.auth.access import get_accessible_project
from app.models import User, Sample, Population, ConsensusGenotype
from app.schemas.sample import ConsensusGenotypeOut, ConsensusEdit
from app.services import consensus as consensus_svc

router = APIRouter(tags=["consensus"])


def _consensus_for_sample(db: Session, sample_id: int):
    return db.scalars(
        select(ConsensusGenotype).where(ConsensusGenotype.sample_id == sample_id)
        .order_by(ConsensusGenotype.marker)
    ).all()


@router.post("/samples/{sample_id}/rerun-consensus", response_model=list[ConsensusGenotypeOut])
def rerun_sample_consensus(
    sample_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    sample = db.get(Sample, sample_id)
    if sample is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sample not found")
    get_accessible_project(sample.project_id, need_edit=True, db=db, user=current)
    consensus_svc.recompute(db, [sample_id])
    db.commit()
    return _consensus_for_sample(db, sample_id)


@router.post("/populations/{population_id}/rerun-consensus")
def rerun_population_consensus(
    population_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    pop = db.get(Population, population_id)
    if pop is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Population not found")
    get_accessible_project(pop.project_id, need_edit=True, db=db, user=current)
    sample_ids = list(db.scalars(select(Sample.id).where(Sample.population_id == population_id)))
    written = consensus_svc.recompute(db, sample_ids)
    db.commit()
    return {"samples": len(sample_ids), "consensus_rows": written}


def _owned_consensus(db: Session, consensus_id: int, current: User) -> ConsensusGenotype:
    row = db.get(ConsensusGenotype, consensus_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Consensus genotype not found")
    sample = db.get(Sample, row.sample_id)
    get_accessible_project(sample.project_id, need_edit=True, db=db, user=current)
    return row


@router.patch("/consensus/{consensus_id}", response_model=ConsensusGenotypeOut)
def edit_consensus(
    consensus_id: int, payload: ConsensusEdit,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    row = _owned_consensus(db, consensus_id, current)
    if row.is_locked:
        raise HTTPException(status.HTTP_409_CONFLICT, "Genotype is locked; unlock it before editing")
    consensus_svc.edit_consensus(db, row, payload.model_dump(exclude_unset=True), current.id)
    db.commit()
    db.refresh(row)
    return row


@router.post("/consensus/{consensus_id}/lock", response_model=ConsensusGenotypeOut)
def lock_consensus(
    consensus_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    row = _owned_consensus(db, consensus_id, current)
    consensus_svc.set_lock(db, row, True, current.id)
    db.commit()
    db.refresh(row)
    return row


@router.post("/consensus/{consensus_id}/unlock", response_model=ConsensusGenotypeOut)
def unlock_consensus(
    consensus_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    row = _owned_consensus(db, consensus_id, current)
    consensus_svc.set_lock(db, row, False, current.id)
    db.commit()
    db.refresh(row)
    return row
