"""Seed a demo project so the M1-M3 UI can be exercised without running a pipeline job.

Creates a demo admin, a project with one population + study, reference alleles, and 7 samples
(two wolves with recaptures — one anchored by a tissue reference, one with a dropout — plus a
singleton). It then runs the real recompute (M2) and matching (M3) so consensus + animals appear.

Usage (SQLite local):
    DATABASE_URL="sqlite+pysqlite:///./local.db" python -m app.seed_demo
"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db import Base, engine, SessionLocal
import app.models  # noqa: F401  register tables
from app.models import (
    User, UserRole, Project, Population, Study,
    Sample, ReferenceAllele, ReplicateObservation, ReplicateAmplification,
)
from app.auth.security import hash_password
from app.services.consensus import recompute
from app.services.matching.runner import run_matching

ADMIN_EMAIL = "demo@example.com"
ADMIN_PASSWORD = "demo1234"
PROJECT_NAME = "Dinaric Wolf Demo"

MARKERS = [f"FH{2001 + i}" for i in range(14)]          # 14 STR-ish markers
WELLS = ["PP1", "PP2", "PP3"]                            # 3 replicate plates
BASE_READS = [520, 480, 505]                            # per-well read baseline

# Animal genotypes as allele indices (0..3) per marker; 4 alleles/marker in the catalog.
ALPHA = (0, 1)
BETA = (2, 3)
SINGLE = (0, 2)

# name, genotype, is_reference, dropout_markers
SAMPLES = [
    ("TISSUE-REF-1", ALPHA, True, set()),
    ("SCAT-001", ALPHA, False, set()),
    ("SCAT-002", ALPHA, False, set()),
    ("SCAT-003", ALPHA, False, {MARKERS[0]}),           # 1 allelic dropout -> still reliable
    ("SCAT-004", BETA, False, set()),
    ("SCAT-005", BETA, False, set()),
    ("SCAT-006", SINGLE, False, set()),                 # distinct individual
]


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if admin is None:
            admin = User(email=ADMIN_EMAIL, password_hash=hash_password(ADMIN_PASSWORD),
                         role=UserRole.admin)
            db.add(admin); db.flush()

        if db.scalar(select(Project).where(Project.owner_user_id == admin.id,
                                           Project.name == PROJECT_NAME)):
            print(f"'{PROJECT_NAME}' already seeded — login {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
            return

        proj = Project(public_id=uuid.uuid4().hex, name=PROJECT_NAME,
                       organisation="DivjaLabs", owner_user_id=admin.id)
        db.add(proj); db.flush()
        pop = Population(project_id=proj.id, name="Dinaric")
        db.add(pop); db.flush()
        study = Study(project_id=proj.id, population_id=pop.id, name="2025 Monitoring")
        db.add(study); db.flush()

        # reference alleles: 4 per marker (a,b,c,d)
        ref: dict = {}
        for m in MARKERS:
            for idx, tag in enumerate("abcd"):
                ra = ReferenceAllele(project_id=proj.id, marker=m, sequence=f"{m}-{tag}",
                                     length=100 + idx, variant=idx + 1, allele_name=tag)
                db.add(ra); ref[(m, idx)] = ra
        db.flush()

        n = 0
        for name, geno, is_ref, dropout in SAMPLES:
            n += 1
            s = Sample(public_id=uuid.uuid4().hex, system_code=f"S-{n:04d}",
                       project_id=proj.id, population_id=pop.id, study_id=study.id, kit_id=1,
                       name=name, genotype_ok=True, is_animal_reference=is_ref)
            db.add(s); db.flush()
            for m in MARKERS:
                alleles = (geno[0],) if m in dropout else geno   # homozygote at dropout marker
                for w, base in zip(WELLS, BASE_READS):
                    db.add(ReplicateAmplification(sample_id=s.id, marker=m, plate=w,
                                                  position=1, run_name="demo"))
                    for k, ai in enumerate(alleles):
                        db.add(ReplicateObservation(
                            sample_id=s.id, marker=m, plate=w, position=1, run_name="demo",
                            read_count=base - k * 30, length=100 + ai, called=True, flag="",
                            sequence=f"{m}-{'abcd'[ai]}", allele_name="abcd"[ai]))
        db.commit()

        sample_ids = list(db.scalars(select(Sample.id).where(Sample.project_id == proj.id)))
        recompute(db, sample_ids); db.commit()
        run_matching(db, pop.id, user_id=admin.id); db.commit()

        print(f"Seeded '{PROJECT_NAME}': {len(sample_ids)} samples, {len(MARKERS)} markers.")
        print(f"Login: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        print(f"Project id {proj.id}, population id {pop.id}")


if __name__ == "__main__":
    seed()
