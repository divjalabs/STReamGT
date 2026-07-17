"""M3: end-to-end matching — recaptures group into one animal, distinct individuals stay apart."""
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    User, Project, Population, Study, Sample, ConsensusGenotype, ReferenceAllele, MatchSubgroup,
)

MARKERS = [f"M{i}" for i in range(1, 15)]          # 14 markers (>= min_shared_loci 12)


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _seed():
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        proj = Project(public_id=uuid.uuid4().hex, name="Wolves", owner_user_id=u.id)
        db.add(proj); db.flush()
        pop = Population(project_id=proj.id, name="Dinaric"); db.add(pop); db.flush()
        db.add(Study(project_id=proj.id, population_id=pop.id, name="2025")); db.flush()

        ref = {}
        for m in MARKERS:
            for tag in ("a", "b"):
                ra = ReferenceAllele(project_id=proj.id, marker=m, sequence=f"{m}{tag}",
                                     allele_name=tag)
                db.add(ra); ref[(m, tag)] = ra
        db.flush()

        n = {"i": 0}

        def sample(name, geno):
            n["i"] += 1
            s = Sample(public_id=uuid.uuid4().hex, system_code=f"S-{n['i']:04d}",
                       project_id=proj.id, population_id=pop.id, name=name, genotype_ok=True)
            db.add(s); db.flush()
            for m in MARKERS:
                a_tag, b_tag = geno(m)             # b_tag None -> homozygote
                db.add(ConsensusGenotype(
                    sample_id=s.id, marker=m,
                    allele1=a_tag, allele1_id=ref[(m, a_tag)].id,
                    allele2=b_tag, allele2_id=ref[(m, b_tag)].id if b_tag else None))
            return s

        het = lambda m: ("a", "b")
        hom = lambda m: ("a", None)
        one_dropout = lambda m: ("a", None) if m == "M1" else ("a", "b")

        s1 = sample("wolf-A1", het)                 # animal X
        s2 = sample("wolf-A2", het)                 # X recapture (identical)
        s3 = sample("wolf-B1", hom)                 # animal Y (homozygous everywhere)
        s4 = sample("wolf-A3", one_dropout)         # X with 1 dropout marker
        db.commit()
        return pop.id, {"X": [s1.id, s2.id, s4.id], "Y": [s3.id]}


def test_matching_groups_recaptures(client, admin_token):
    pop_id, expect = _seed()

    r = client.post(f"/api/populations/{pop_id}/rerun-match", headers=_hdr(admin_token))
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "succeeded"
    assert run["n_samples"] == 4
    assert run["n_subgroups"] == 2                  # animal X + animal Y

    subs = client.get(f"/api/populations/{pop_id}/subgroups", headers=_hdr(admin_token)).json()
    assert len(subs) == 2
    sizes = sorted(s["n_samples"] for s in subs)
    assert sizes == [1, 3]                          # {S3} and {S1,S2,S4}

    # the three X samples share one subgroup; Y is separate
    with SessionLocal() as db:
        sg = {sid: db.get(Sample, sid).subgroup_id for grp in expect.values() for sid in grp}
        xs = [sg[i] for i in expect["X"]]
        assert xs[0] is not None and len(set(xs)) == 1      # all X in one animal
        assert sg[expect["Y"][0]] not in xs                 # Y in a different animal

    # matches: the dropout recapture (a DISTINCT genotype) reliably matches X's reference;
    # X-vs-Y is not a match. (The two identical recaptures X[0]/X[1] are exact-collapsed, so they
    # share the animal via membership rather than a pairwise match row.)
    matches = client.get(f"/api/populations/{pop_id}/matches", headers=_hdr(admin_token)).json()
    pairs = {frozenset((m["sample_a_id"], m["sample_b_id"])): m["tier"] for m in matches}
    assert pairs[frozenset((expect["X"][0], expect["X"][2]))] == "reliable"   # s1 (het) vs s4 (dropout)
    assert frozenset((expect["X"][0], expect["Y"][0])) not in pairs


def test_matching_settings_update(client, admin_token):
    pop_id, _ = _seed()
    r = client.get(f"/api/populations/{pop_id}/matching-settings", headers=_hdr(admin_token))
    assert r.status_code == 200 and r.json()["min_shared_loci"] == 12
    r = client.put(f"/api/populations/{pop_id}/matching-settings",
                   json={"min_shared_loci": 13, "use_pi_gate": True}, headers=_hdr(admin_token))
    assert r.status_code == 200 and r.json()["min_shared_loci"] == 13 and r.json()["use_pi_gate"] is True
