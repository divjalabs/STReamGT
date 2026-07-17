"""Sample-detail enrichment for the redesigned sample page: N.Al1/N.Al2 observation counts,
kit_code, animal_label, sex_marker; editable genotype_ok; plot-data stutter; project sample list."""
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    User, Project, Population, Study, Sample, ConsensusGenotype, ReplicateObservation,
    MatchSubgroup, Kit,
)

A, B = "A" * 12, "A" * 14


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _seed(with_match=False):
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        kit = db.scalar(select(Kit).where(Kit.kit_code == "DKIT")) or Kit(kit_code="DKIT")
        db.add(kit); db.flush()
        proj = Project(public_id=uuid.uuid4().hex, name="P", owner_user_id=u.id); db.add(proj); db.flush()
        pop = Population(project_id=proj.id, name="Pop"); db.add(pop); db.flush()
        s = Sample(public_id=uuid.uuid4().hex, system_code=f"S-{uuid.uuid4().hex[:6]}",
                   project_id=proj.id, population_id=pop.id, kit_id=kit.id, name="w1")
        db.add(s); db.flush()
        # M1 het 12/14 seen in 3 replicates of allele 12 and 2 of allele 14
        for tc, al, seq in [("T1", "12", A), ("T2", "12", A), ("T3", "12", A),
                            ("T1", "14", B), ("T2", "14", B)]:
            db.add(ReplicateObservation(sample_id=s.id, marker="M1", plate="PP1", position=1,
                                        tag_combo=tc, read_count=500, length=len(seq), called=True,
                                        flag="", stutter=(al == "14"), sequence=seq, allele_name=al))
        db.add(ConsensusGenotype(sample_id=s.id, marker="M1", allele1="12", allele2="14"))
        if with_match:
            sg = MatchSubgroup(public_id=uuid.uuid4().hex, population_id=pop.id, label="ANIMAL-7",
                               n_samples=1)
            db.add(sg); db.flush()
            s.subgroup_id = sg.id
        db.commit()
        return proj.id, s.id


def test_sample_detail_enrichment(client, admin_token):
    pid, sid = _seed(with_match=True)
    d = client.get(f"/api/samples/{sid}", headers=_hdr(admin_token)).json()
    assert d["kit_code"] == "DKIT"
    assert d["animal_label"] == "ANIMAL-7"
    assert d["sex_marker"] == "SRY"
    row = d["consensus"][0]
    assert row["n_obs_a1"] == 3 and row["n_obs_a2"] == 2   # 3× allele "12", 2× allele "14"


def test_edit_genotype_ok(client, admin_token):
    pid, sid = _seed()
    r = client.patch(f"/api/samples/{sid}", json={"genotype_ok": True}, headers=_hdr(admin_token))
    assert r.status_code == 200 and r.json()["genotype_ok"] is True
    r = client.patch(f"/api/samples/{sid}", json={"genotype_ok": False}, headers=_hdr(admin_token))
    assert r.json()["genotype_ok"] is False


def test_plot_data_has_stutter(client, admin_token):
    pid, sid = _seed()
    plots = client.get(f"/api/samples/{sid}/plot-data", headers=_hdr(admin_token)).json()
    pts = plots[0]["points"]
    assert any(p["stutter"] for p in pts) and any(not p["stutter"] for p in pts)


def test_project_samples_listing(client, admin_token):
    pid, sid = _seed()
    r = client.get(f"/api/projects/{pid}/samples", headers=_hdr(admin_token))
    assert r.status_code == 200 and [s["id"] for s in r.json()] == [sid]
