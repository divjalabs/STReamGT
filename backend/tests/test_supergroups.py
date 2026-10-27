"""M4 extras: supergroup QC (cross-subgroup crossmatch) and the project access-list endpoint."""
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User, Project, Population, Study, Sample, ConsensusGenotype, ReferenceAllele

MARKERS = [f"M{i}" for i in range(14)]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _seed_crossmatch():
    """R1 & R2 are distinct animals (3 dropouts apart); B reliably matches BOTH -> links them."""
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        proj = Project(public_id=uuid.uuid4().hex, name="X", owner_user_id=u.id); db.add(proj); db.flush()
        pop = Population(project_id=proj.id, name="P"); db.add(pop); db.flush()
        db.add(Study(project_id=proj.id, population_id=pop.id, name="S")); db.flush()
        ref = {}
        for m in MARKERS:
            for tag in ("a", "b"):
                ra = ReferenceAllele(project_id=proj.id, marker=m, sequence=f"{m}{tag}", allele_name=tag)
                db.add(ra); ref[(m, tag)] = ra
        db.flush()
        n = {"i": 0}

        def sample(name, hom_from, is_ref):
            n["i"] += 1
            s = Sample(public_id=uuid.uuid4().hex, system_code=f"S-{n['i']:04d}", project_id=proj.id,
                       population_id=pop.id, name=name, genotype_ok=True, is_animal_reference=is_ref)
            db.add(s); db.flush()
            for i, m in enumerate(MARKERS):
                homo = i >= hom_from                      # dropout (homozygote 'a') from this index on
                db.add(ConsensusGenotype(
                    sample_id=s.id, marker=m, allele1="a", allele1_id=ref[(m, "a")].id,
                    allele2=None if homo else "b", allele2_id=None if homo else ref[(m, "b")].id))
            return s

        r1 = sample("R1", 14, True)     # het at all 14
        r2 = sample("R2", 11, True)     # homozygous from M11 -> 3 dropouts vs R1
        b = sample("B", 13, False)      # homozygous only at M13 -> 1 ADO vs R1, 2 ADO vs R2
        db.commit()
        return pop.id, r1.id, r2.id, b.id


def test_supergroup_links_animals(client, admin_token):
    pop_id, r1, r2, b = _seed_crossmatch()
    run = client.post(f"/api/populations/{pop_id}/rerun-match", headers=_hdr(admin_token)).json()
    assert run["status"] == "succeeded"
    assert run["n_subgroups"] == 2                       # R1's animal and R2's animal

    subs = client.get(f"/api/populations/{pop_id}/subgroups", headers=_hdr(admin_token)).json()
    assert len(subs) == 2
    sups = client.get(f"/api/populations/{pop_id}/supergroups", headers=_hdr(admin_token)).json()
    assert len(sups) == 1                                 # a crossmatch links the two animals
    assert set(sups[0]["subgroup_ids"]) == {s["id"] for s in subs}


def test_project_access_list(client, admin_token, user_token):
    pid = client.post("/api/projects", json={"name": "P"}, headers=_hdr(admin_token)).json()["id"]
    r = client.get(f"/api/projects/{pid}/access", headers=_hdr(admin_token))
    assert r.status_code == 200
    assert r.json()["owner_email"] == "admin@x.com" and r.json()["members"] == []

    client.post(f"/api/projects/{pid}/share", json={"email": "user@x.com", "role": "editor"},
                headers=_hdr(admin_token))
    members = client.get(f"/api/projects/{pid}/access", headers=_hdr(admin_token)).json()["members"]
    assert len(members) == 1 and members[0]["email"] == "user@x.com" and members[0]["role"] == "editor"
