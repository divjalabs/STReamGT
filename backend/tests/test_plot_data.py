"""Per-sample plot-data + kit/study sibling-sample endpoints."""
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    User, Project, Population, Study, Sample, ConsensusGenotype, ReplicateObservation,
)

A, B = "A" * 12, "A" * 14   # lengths 12 / 14


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _seed():
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        proj = Project(public_id=uuid.uuid4().hex, name="P", owner_user_id=u.id)
        db.add(proj); db.flush()
        pop = Population(project_id=proj.id, name="Pop"); db.add(pop); db.flush()
        study = Study(project_id=proj.id, population_id=pop.id, name="St"); db.add(study); db.flush()
        s = Sample(public_id=uuid.uuid4().hex, system_code="S-0001", project_id=proj.id,
                   population_id=pop.id, study_id=study.id, kit_id=7, name="w1")
        db.add(s); db.flush()
        # M1 heterozygote 12/14 across two replicates (tag combos), M2 homozygote 12
        for well, tc in [("PP1", "T1"), ("PP2", "T2")]:
            db.add_all([
                ReplicateObservation(sample_id=s.id, marker="M1", plate=well, position=1,
                                     tag_combo=tc, read_count=500, length=12, called=True,
                                     flag="", sequence=A, allele_name="12"),
                ReplicateObservation(sample_id=s.id, marker="M1", plate=well, position=1,
                                     tag_combo=tc, read_count=480, length=14, called=True,
                                     flag="", sequence=B, allele_name="14"),
                ReplicateObservation(sample_id=s.id, marker="M2", plate=well, position=1,
                                     tag_combo=tc, read_count=600, length=12, called=True,
                                     flag="L", sequence=A, allele_name="12"),
            ])
        db.add_all([
            ConsensusGenotype(sample_id=s.id, marker="M1", allele1="12", allele2="14"),
            ConsensusGenotype(sample_id=s.id, marker="M2", allele1="12"),
        ])
        db.commit()
        return s.id, study.id, 7


def test_plot_data(client, admin_token):
    sid, study_id, kit_id = _seed()
    r = client.get(f"/api/samples/{sid}/plot-data", headers=_hdr(admin_token))
    assert r.status_code == 200
    plots = {p["marker"]: p for p in r.json()}
    assert set(plots) == {"M1", "M2"}
    m1 = plots["M1"]
    assert m1["title"] == "M1: 12/14"                 # consensus alleles in the title
    assert len(m1["lines"]) == 2                       # one polyline per replicate (T1, T2)
    assert len(m1["lines"][0]) == 2                    # each line has 2 points (len 12 + 14)
    assert len(m1["points"]) == 4
    assert plots["M2"]["title"] == "M2: 12"
    assert all(p["flagged"] for p in plots["M2"]["points"])   # M2 obs are flagged (flag "L")

    # marker filter
    r = client.get(f"/api/samples/{sid}/plot-data?markers=M2", headers=_hdr(admin_token))
    assert [p["marker"] for p in r.json()] == ["M2"]


def test_kit_and_study_sample_listing(client, admin_token):
    sid, study_id, kit_id = _seed()
    r = client.get(f"/api/studies/{study_id}/samples", headers=_hdr(admin_token))
    assert r.status_code == 200 and [s["id"] for s in r.json()] == [sid]
    r = client.get(f"/api/kits/{kit_id}/samples", headers=_hdr(admin_token))
    assert r.status_code == 200 and [s["id"] for s in r.json()] == [sid]

    # a user with no project access sees nothing / 404
    tok2 = client.post("/api/auth/register",
                       json={"email": "z@x.com", "password": "zpass1234"}).json()["access_token"]
    assert client.get(f"/api/kits/{kit_id}/samples", headers=_hdr(tok2)).json() == []
    assert client.get(f"/api/studies/{study_id}/samples", headers=_hdr(tok2)).status_code == 404
