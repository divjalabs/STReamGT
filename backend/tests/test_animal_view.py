"""Individual animal page: detail counts, single-animal rematch (per-locus), reference change +
reliably-genotyped override, and override persistence across a full population rerun."""
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    User, Project, Population, Study, Sample, ConsensusGenotype, ReferenceAllele, AnimalOverride,
)

MARKERS = [f"M{i}" for i in range(1, 15)]      # 14 markers ≥ min_shared_loci (12)


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _seed():
    """Animal X = 3 het samples (one with a dropout on M1); animal Y = 1 homozygous sample."""
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        proj = Project(public_id=uuid.uuid4().hex, name="Wolves", owner_user_id=u.id); db.add(proj); db.flush()
        pop = Population(project_id=proj.id, name="Dinaric"); db.add(pop); db.flush()
        db.add(Study(project_id=proj.id, population_id=pop.id, name="2025")); db.flush()
        ref = {}
        for m in MARKERS:
            for tag in ("a", "b"):
                ra = ReferenceAllele(project_id=proj.id, marker=m, sequence=f"{m}{tag}", allele_name=tag)
                db.add(ra); ref[(m, tag)] = ra
        db.flush()
        ids = {}

        def sample(name, geno):
            s = Sample(public_id=uuid.uuid4().hex, system_code=f"S-{name}", project_id=proj.id,
                       population_id=pop.id, name=name, genotype_ok=True)
            db.add(s); db.flush()
            for m in MARKERS:
                a_tag, b_tag = geno(m)
                db.add(ConsensusGenotype(sample_id=s.id, marker=m,
                                         allele1=a_tag, allele1_id=ref[(m, a_tag)].id,
                                         allele2=b_tag, allele2_id=ref[(m, b_tag)].id if b_tag else None))
            ids[name] = s.id
            return s

        sample("X1", lambda m: ("a", "b"))
        sample("X2", lambda m: ("a", "b"))
        sample("X3", lambda m: ("a", None) if m == "M1" else ("a", "b"))   # dropout on M1
        sample("Y1", lambda m: ("a", None))
        db.commit()
        return pop.id, ids


def _x_subgroup(client, tok, pop_id):
    subs = client.get(f"/api/populations/{pop_id}/subgroups", headers=_hdr(tok)).json()
    return next(s for s in subs if s["n_samples"] == 3)     # animal X has 3 members


def test_animal_detail_and_rematch(client, admin_token):
    pop_id, ids = _seed()
    assert client.post(f"/api/populations/{pop_id}/rerun-match", headers=_hdr(admin_token)).status_code == 200
    x = _x_subgroup(client, admin_token, pop_id)

    d = client.get(f"/api/subgroups/{x['id']}", headers=_hdr(admin_token)).json()
    assert d["n_samples"] == 3 and d["n_reliable"] == 3
    assert d["reliably_genotyped"] is False
    assert {m["system_code"] for m in d["members"]} == {"S-X1", "S-X2", "S-X3"}
    assert sum(m["is_reference"] for m in d["members"]) == 1

    rm = client.post(f"/api/subgroups/{x['id']}/rematch", headers=_hdr(admin_token)).json()
    ref_rows = [m for m in rm["matches"] if m["is_reference"]]
    cand = [m for m in rm["matches"] if not m["is_reference"]]
    assert len(ref_rows) == 1
    assert len(cand) == 2 and all(m["reliable"] for m in cand)    # X's other two samples
    # the dropout sample mismatches exactly at M1 (an ADO-type code)
    drop = next(m for m in cand if m["system_code"] == "S-X3")
    assert drop["num_ado_mm"] == 1 and drop["num_total_ic"] == 0
    assert [mm["marker"] for mm in drop["mismatches"]] == ["M1"]
    # genotype grid: 14 markers, reference column flagged, the M1 cell of the dropout sample tinted
    assert len(rm["genotypes"]["markers"]) == 14
    drop_col = next(s for s in rm["genotypes"]["samples"] if s["sample_id"] == ids["X3"])
    assert drop_col["cells"]["M1"]["mismatch"] is True
    assert drop_col["cells"]["M2"]["mismatch"] is False


def test_reliably_genotyped_and_reference_change_persist(client, admin_token):
    pop_id, ids = _seed()
    client.post(f"/api/populations/{pop_id}/rerun-match", headers=_hdr(admin_token))
    x = _x_subgroup(client, admin_token, pop_id)

    # set reliably-genotyped and pin the reference to X3
    client.patch(f"/api/subgroups/{x['id']}", json={"reliably_genotyped": True}, headers=_hdr(admin_token))
    d = client.patch(f"/api/subgroups/{x['id']}",
                     json={"reference_sample_id": ids["X3"]}, headers=_hdr(admin_token)).json()
    assert d["reference_sample_id"] == ids["X3"] and d["reference_system_code"] == "S-X3"
    assert d["reliably_genotyped"] is True
    with SessionLocal() as db:
        assert db.get(Sample, ids["X3"]).is_animal_reference is True

    # a FULL population rerun recreates subgroups — the override (keyed by the pinned reference) survives
    client.post(f"/api/populations/{pop_id}/rerun-match", headers=_hdr(admin_token))
    x2 = _x_subgroup(client, admin_token, pop_id)
    d2 = client.get(f"/api/subgroups/{x2['id']}", headers=_hdr(admin_token)).json()
    assert d2["reference_sample_id"] == ids["X3"]          # pin held
    assert d2["reliably_genotyped"] is True                # override persisted
    with SessionLocal() as db:
        assert db.scalar(select(AnimalOverride).where(
            AnimalOverride.reference_sample_id == ids["X3"])).reliably_genotyped is True


def test_reference_must_be_member(client, admin_token):
    pop_id, ids = _seed()
    client.post(f"/api/populations/{pop_id}/rerun-match", headers=_hdr(admin_token))
    x = _x_subgroup(client, admin_token, pop_id)
    # Y1 is a different animal → rejected
    r = client.patch(f"/api/subgroups/{x['id']}",
                     json={"reference_sample_id": ids["Y1"]}, headers=_hdr(admin_token))
    assert r.status_code == 422
