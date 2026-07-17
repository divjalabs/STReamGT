"""Projects and their populations / studies / sample-types + sharing.

A project is the container for the animal/sample/consensus/matching data. Access is via
app.auth.access (owner / admin / project_access), decoupled from kit_access.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, or_, func
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.auth.deps import get_current_user
from app.auth.access import get_accessible_project
from app.models import (
    User, Project, Population, Study, SampleType, Sample, Kit, ProjectRole,
)
from app.models.project import project_access
from app.schemas.project import (
    ProjectCreate, ProjectOut, PopulationCreate, PopulationOut,
    StudyCreate, StudyOut, SampleTypeCreate, SampleTypeOut, ShareRequest,
    ProjectAccessOut, ProjectMemberOut,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    if current.is_admin:
        return db.scalars(select(Project).order_by(Project.created_at.desc())).all()
    shared_ids = select(project_access.c.project_id).where(
        project_access.c.user_id == current.id
    )
    return db.scalars(
        select(Project)
        .where(or_(Project.owner_user_id == current.id, Project.id.in_(shared_ids)))
        .order_by(Project.created_at.desc())
    ).all()


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate, db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if db.scalar(select(Project).where(
        Project.owner_user_id == current.id, Project.name == payload.name
    )):
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a project with that name")
    project = Project(
        public_id=uuid.uuid4().hex, name=payload.name,
        organisation=payload.organisation, description=payload.description,
        owner_user_id=current.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    return get_accessible_project(project_id, db=db, user=current)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    """Permanently delete a project and ALL its data. Owner (or admin) only."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if not current.is_admin and project.owner_user_id != current.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the project owner can delete it")
    from app.services.project_admin import delete_project as _delete
    _delete(db, project_id)


# ---- populations ----

@router.get("/{project_id}/populations", response_model=list[PopulationOut])
def list_populations(
    project_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    get_accessible_project(project_id, db=db, user=current)
    pops = db.scalars(
        select(Population).where(Population.project_id == project_id).order_by(Population.name)
    ).all()
    counts = dict(db.execute(
        select(Sample.population_id, func.count())
        .where(Sample.project_id == project_id, Sample.population_id.is_not(None))
        .group_by(Sample.population_id)
    ).all())
    for p in pops:
        p.sample_count = counts.get(p.id, 0)   # transient attr; read by PopulationOut
    return pops


@router.post("/{project_id}/populations", response_model=PopulationOut,
             status_code=status.HTTP_201_CREATED)
def create_population(
    project_id: int, payload: PopulationCreate,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    get_accessible_project(project_id, need_edit=True, db=db, user=current)
    if db.scalar(select(Population).where(
        Population.project_id == project_id, Population.name == payload.name
    )):
        raise HTTPException(status.HTTP_409_CONFLICT, "population name already exists in project")
    pop = Population(project_id=project_id, name=payload.name,
                     description=payload.description)
    db.add(pop)
    db.commit()
    db.refresh(pop)
    pop.sample_count = 0
    return pop


@router.delete("/{project_id}/populations/{population_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_population(
    project_id: int, population_id: int,
    reassign_to: int | None = None, delete_samples: bool = False,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    """Delete a population. If it still has samples, either `reassign_to` another population (its
    samples + studies move there) or pass `delete_samples=true` to delete them; otherwise 409."""
    get_accessible_project(project_id, need_edit=True, db=db, user=current)
    pop = db.get(Population, population_id)
    if pop is None or pop.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Population not found")

    n_samples = db.scalar(
        select(func.count()).select_from(Sample).where(Sample.population_id == population_id)
    )
    if n_samples and reassign_to is None and not delete_samples:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Population has {n_samples} sample(s); pass reassign_to=<population_id> to transfer "
            f"them or delete_samples=true to delete them.",
        )
    if reassign_to is not None:
        target = db.get(Population, reassign_to)
        if target is None or target.project_id != project_id or target.id == population_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "reassign_to must be another population in this project")

    from app.services.population_admin import delete_population as _delete
    _delete(db, pop, reassign_to_id=reassign_to, delete_samples=delete_samples)


# ---- studies ----

@router.get("/{project_id}/studies", response_model=list[StudyOut])
def list_studies(
    project_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    get_accessible_project(project_id, db=db, user=current)
    return db.scalars(
        select(Study).where(Study.project_id == project_id)
        .options(selectinload(Study.kits)).order_by(Study.name)
    ).all()


@router.post("/{project_id}/studies", response_model=StudyOut, status_code=status.HTTP_201_CREATED)
def create_study(
    project_id: int, payload: StudyCreate,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    get_accessible_project(project_id, need_edit=True, db=db, user=current)
    if payload.population_id is not None:
        pop = db.get(Population, payload.population_id)
        if pop is None or pop.project_id != project_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "population_id is not in this project")
    if db.scalar(select(Study).where(
        Study.project_id == project_id, Study.name == payload.name
    )):
        raise HTTPException(status.HTTP_409_CONFLICT, "study name already exists in project")
    study = Study(project_id=project_id, population_id=payload.population_id, name=payload.name,
                  include_in_matching=payload.include_in_matching, description=payload.description)
    db.add(study)
    db.commit()
    db.refresh(study)
    return study


# ---- single-study endpoints (kit attachment) — mounted at /studies, not /projects ----

studies_router = APIRouter(prefix="/studies", tags=["studies"])


def _get_editable_study(study_id: int, db: Session, current: User) -> Study:
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Study not found")
    get_accessible_project(study.project_id, need_edit=True, db=db, user=current)
    return study


@studies_router.get("/{study_id}", response_model=StudyOut)
def get_study(
    study_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Study not found")
    get_accessible_project(study.project_id, db=db, user=current)
    return study


@studies_router.post("/{study_id}/kits/{kit_id}", response_model=StudyOut)
def attach_kit(
    study_id: int, kit_id: int,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    study = _get_editable_study(study_id, db, current)
    kit = db.get(Kit, kit_id)
    if kit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kit not found")
    if not current.is_admin and not any(u.id == current.id for u in kit.users):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this kit")
    if not any(k.id == kit.id for k in study.kits):
        study.kits.append(kit)
        db.commit()
    db.refresh(study)
    return study


@studies_router.delete("/{study_id}/kits/{kit_id}", response_model=StudyOut)
def detach_kit(
    study_id: int, kit_id: int,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    study = _get_editable_study(study_id, db, current)
    kit = next((k for k in study.kits if k.id == kit_id), None)
    if kit is not None:
        study.kits.remove(kit)
        db.commit()
    db.refresh(study)
    return study


@studies_router.delete("/{study_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_study(
    study_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    """Delete a study; its samples stay, falling back to the study's parent population."""
    study = _get_editable_study(study_id, db, current)
    from app.services.population_admin import delete_study as _delete
    _delete(db, study)


# ---- sample types ----

@router.get("/{project_id}/sample-types", response_model=list[SampleTypeOut])
def list_sample_types(
    project_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    get_accessible_project(project_id, db=db, user=current)
    return db.scalars(
        select(SampleType).where(
            or_(SampleType.project_id == project_id, SampleType.project_id.is_(None))
        ).order_by(SampleType.code)
    ).all()


@router.post("/{project_id}/sample-types", response_model=SampleTypeOut,
             status_code=status.HTTP_201_CREATED)
def create_sample_type(
    project_id: int, payload: SampleTypeCreate,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    get_accessible_project(project_id, need_edit=True, db=db, user=current)
    st = SampleType(project_id=project_id, code=payload.code, name=payload.name,
                    exclude_from_analysis=payload.exclude_from_analysis,
                    reliable_sample_type=payload.reliable_sample_type)
    db.add(st)
    db.commit()
    db.refresh(st)
    return st


# ---- sharing ----

@router.get("/{project_id}/access", response_model=ProjectAccessOut)
def list_access(
    project_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    project = get_accessible_project(project_id, db=db, user=current)
    owner = db.get(User, project.owner_user_id)
    rows = db.execute(
        select(project_access.c.user_id, project_access.c.role, User.email)
        .join(User, User.id == project_access.c.user_id)
        .where(project_access.c.project_id == project_id)
        .order_by(User.email)
    ).all()
    return ProjectAccessOut(
        owner_user_id=owner.id, owner_email=owner.email,
        members=[ProjectMemberOut(user_id=r.user_id, email=r.email, role=r.role) for r in rows],
    )


@router.post("/{project_id}/share", status_code=status.HTTP_204_NO_CONTENT)
def share_project(
    project_id: int, payload: ShareRequest,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    project = get_accessible_project(project_id, need_edit=True, db=db, user=current)
    target = db.scalar(select(User).where(User.email == payload.email))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if target.id == project.owner_user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "user is the project owner")
    exists = db.execute(select(project_access.c.user_id).where(
        project_access.c.project_id == project_id, project_access.c.user_id == target.id
    )).first()
    if exists:
        db.execute(project_access.update().where(
            project_access.c.project_id == project_id, project_access.c.user_id == target.id
        ).values(role=payload.role))
    else:
        db.execute(project_access.insert().values(
            project_id=project_id, user_id=target.id, role=payload.role
        ))
    db.commit()


@router.delete("/{project_id}/share/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def unshare_project(
    project_id: int, user_id: int,
    db: Session = Depends(get_db), current: User = Depends(get_current_user),
):
    get_accessible_project(project_id, need_edit=True, db=db, user=current)
    db.execute(project_access.delete().where(
        project_access.c.project_id == project_id, project_access.c.user_id == user_id
    ))
    db.commit()
