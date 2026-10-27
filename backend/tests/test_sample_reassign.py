"""Assign/reassign a sample to a population (Project > population page dropdown)."""
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User, Project, Population, Sample


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _seed():
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@x.com"))
        proj = Project(public_id=uuid.uuid4().hex, name="P", owner_user_id=u.id)
        other = Project(public_id=uuid.uuid4().hex, name="Other", owner_user_id=u.id)
        db.add_all([proj, other]); db.flush()
        p1 = Population(project_id=proj.id, name="Pop1")
        p2 = Population(project_id=proj.id, name="Pop2")
        p_other = Population(project_id=other.id, name="X")
        db.add_all([p1, p2, p_other]); db.flush()
        s = Sample(public_id=uuid.uuid4().hex, system_code="S-0001", project_id=proj.id,
                   population_id=p1.id, name="w1")
        db.add(s); db.commit()
        return s.id, p1.id, p2.id, p_other.id


def test_reassign_sample_population(client, admin_token):
    sid, p1, p2, p_other = _seed()

    # the population endpoint carries project_id (so the page can list the dropdown options)
    r = client.get(f"/api/populations/{p1}", headers=_hdr(admin_token))
    assert r.status_code == 200 and "project_id" in r.json()

    # sample starts in Pop1
    assert [x["id"] for x in client.get(f"/api/populations/{p1}/samples", headers=_hdr(admin_token)).json()] == [sid]

    # reassign to Pop2
    r = client.patch(f"/api/samples/{sid}", json={"population_id": p2}, headers=_hdr(admin_token))
    assert r.status_code == 200 and r.json()["population_id"] == p2

    assert client.get(f"/api/populations/{p1}/samples", headers=_hdr(admin_token)).json() == []
    assert [x["id"] for x in client.get(f"/api/populations/{p2}/samples", headers=_hdr(admin_token)).json()] == [sid]

    # a population from another project is rejected
    assert client.patch(f"/api/samples/{sid}", json={"population_id": p_other},
                        headers=_hdr(admin_token)).status_code == 422
