"""Import / export of a project's structured data.

Export: genotype-matrix CSV, sample-metadata CSV, animals CSV, GenePop, and a full project JSON
(round-trips with import). Import: a genotype-matrix CSV (samples + consensus) and a project JSON.

Allele identity is a sequence (reference_alleles). Imported CSV genotypes carry only allele NAMES,
so we align each name to an existing reference allele of the same (marker, name), else synthesise a
stable identity `<marker>:<name>` — imported data then matches other data by name.
"""
from __future__ import annotations

import csv
import io
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Project, Population, Study, SampleType, Sample, ConsensusGenotype, ReferenceAllele,
    MatchSubgroup, Sex, ConsensusSource,
)


# ----------------------------- shared load -----------------------------

def _load(db: Session, project_id: int):
    project = db.get(Project, project_id)
    pops = {p.id: p for p in db.scalars(select(Population).where(Population.project_id == project_id))}
    studies = {s.id: s for s in db.scalars(select(Study).where(Study.project_id == project_id))}
    samples = db.scalars(
        select(Sample).where(Sample.project_id == project_id).order_by(Sample.system_code)).all()
    cons: dict = defaultdict(dict)
    for cg in db.scalars(select(ConsensusGenotype).join(Sample)
                         .where(Sample.project_id == project_id)):
        cons[cg.sample_id][cg.marker] = cg
    subgroups = {sg.id: sg for sg in db.scalars(
        select(MatchSubgroup).where(MatchSubgroup.population_id.in_(pops.keys() or [0])))}
    markers = sorted({m for d in cons.values() for m in d})
    return project, pops, studies, samples, cons, subgroups, markers


def _animal_label(s: Sample, subgroups) -> str:
    sg = subgroups.get(s.subgroup_id) if s.subgroup_id else None
    return (sg.label or f"animal-{sg.id}") if sg else ""


# ----------------------------- exports -----------------------------

def genotypes_csv(db: Session, project_id: int) -> str:
    _p, pops, studies, samples, cons, _sg, markers = _load(db, project_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    header = ["system_code", "name", "population", "study"]
    for m in markers:
        header += [f"{m}_1", f"{m}_2"]
    w.writerow(header)
    for s in samples:
        row = [s.system_code, s.name,
               pops[s.population_id].name if s.population_id in pops else "",
               studies[s.study_id].name if s.study_id in studies else ""]
        for m in markers:
            cg = cons[s.id].get(m)
            row += [cg.allele1 or "" if cg else "", cg.allele2 or "" if cg else ""]
        w.writerow(row)
    return buf.getvalue()


def metadata_csv(db: Session, project_id: int) -> str:
    _p, pops, studies, samples, _c, subgroups, _m = _load(db, project_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["system_code", "name", "population", "study", "kit_id", "sex", "genotype_ok",
                "discard", "quality_index", "n_replicates", "animal"])
    for s in samples:
        w.writerow([s.system_code, s.name,
                    pops[s.population_id].name if s.population_id in pops else "",
                    studies[s.study_id].name if s.study_id in studies else "",
                    s.kit_id or "", s.sex.value, s.genotype_ok, s.discard_sample,
                    "" if s.quality_index is None else round(s.quality_index, 4),
                    s.n_replicates if s.n_replicates is not None else "",
                    _animal_label(s, subgroups)])
    return buf.getvalue()


def animals_csv(db: Session, project_id: int) -> str:
    _p, pops, _st, samples, _c, subgroups, _m = _load(db, project_id)
    members: dict = defaultdict(list)
    code = {s.id: s.system_code for s in samples}
    for s in samples:
        if s.subgroup_id:
            members[s.subgroup_id].append(s.system_code)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["animal", "population", "reference_sample", "n_samples", "members"])
    for sg in subgroups.values():
        w.writerow([sg.label or f"animal-{sg.id}",
                    pops[sg.population_id].name if sg.population_id in pops else "",
                    code.get(sg.reference_sample_id, ""),
                    len(members.get(sg.id, [])), ";".join(sorted(members.get(sg.id, [])))])
    return buf.getvalue()


def genepop(db: Session, project_id: int) -> str:
    project, pops, _st, samples, cons, _sg, markers = _load(db, project_id)
    # per-marker allele-name -> 3-digit numeric code
    codes: dict = {}
    for m in markers:
        names = sorted({cg.allele1 for s in samples for cg in [cons[s.id].get(m)] if cg and cg.allele1}
                       | {cg.allele2 for s in samples for cg in [cons[s.id].get(m)] if cg and cg.allele2})
        codes[m] = {}
        for i, name in enumerate(names, start=1):
            codes[m][name] = f"{int(name):03d}" if name.isdigit() and int(name) < 1000 else f"{i:03d}"

    def geno(cg, m):
        if cg is None or not cg.allele1:
            return "000000"
        a1 = codes[m].get(cg.allele1, "000")
        a2 = codes[m].get(cg.allele2, a1) if cg.allele2 else a1   # homozygote repeats
        return a1 + a2

    lines = [f"STReamGT export: {project.name}"]
    lines += list(markers)
    by_pop: dict = defaultdict(list)
    for s in samples:
        by_pop[pops[s.population_id].name if s.population_id in pops else "Unknown"].append(s)
    for pop_name, ss in by_pop.items():
        lines.append("Pop")
        for s in ss:
            row = " ".join(geno(cons[s.id].get(m), m) for m in markers)
            lines.append(f"{s.system_code} , {row}")
    return "\n".join(lines) + "\n"


def project_json(db: Session, project_id: int) -> dict:
    project, pops, studies, samples, cons, subgroups, _m = _load(db, project_id)
    ref = {r.id: r for r in db.scalars(
        select(ReferenceAllele).where(ReferenceAllele.project_id == project_id))}

    def seq_of(allele_id):
        r = ref.get(allele_id)
        return r.sequence if r else None

    return {
        "project": {"name": project.name, "organisation": project.organisation,
                    "description": project.description},
        "populations": [{"name": p.name, "description": p.description}
                        for p in pops.values()],
        "studies": [{"name": s.name,
                     "population": pops[s.population_id].name if s.population_id in pops else None,
                     "include_in_matching": s.include_in_matching} for s in studies.values()],
        "reference_alleles": [{"marker": r.marker, "sequence": r.sequence, "length": r.length,
                               "variant": r.variant, "allele_name": r.allele_name, "n": r.n}
                              for r in ref.values()],
        "samples": [{
            "system_code": s.system_code, "name": s.name,
            "population": pops[s.population_id].name if s.population_id in pops else None,
            "study": studies[s.study_id].name if s.study_id in studies else None,
            "sex": s.sex.value, "sex_locked": s.sex_locked, "discard_sample": s.discard_sample,
            "is_animal_reference": s.is_animal_reference, "genotype_ok": s.genotype_ok,
            "animal": _animal_label(s, subgroups),
            "consensus": [{
                "marker": cg.marker, "allele1": cg.allele1, "allele2": cg.allele2,
                "allele1_seq": seq_of(cg.allele1_id), "allele2_seq": seq_of(cg.allele2_id),
                "quality_index": cg.quality_index, "success_rate": cg.success_rate,
                "n_amp": cg.n_amp, "ado": cg.ado,
            } for cg in cons[s.id].values()],
        } for s in samples],
    }


# ----------------------------- import helpers -----------------------------

def _allele_resolver(db: Session, project_id: int):
    """Resolve an allele to a reference_alleles id. By sequence when given (JSON round-trip),
    else align by (marker, name) to an existing allele, else synthesise `<marker>:<name>`."""
    by_seq: dict = {}
    by_name: dict = {}
    for r in db.scalars(select(ReferenceAllele).where(ReferenceAllele.project_id == project_id)):
        by_seq[(r.marker, r.sequence)] = r
        by_name.setdefault((r.marker, r.allele_name), r)

    def resolve(marker: str, name, sequence=None):
        if not name:
            return None
        if sequence:
            r = by_seq.get((marker, sequence))
            if r is None:
                r = ReferenceAllele(project_id=project_id, marker=marker, sequence=sequence,
                                    allele_name=name)
                db.add(r); db.flush()
                by_seq[(marker, sequence)] = r
                by_name.setdefault((marker, name), r)
            return r.id
        r = by_name.get((marker, name))
        if r is None:
            seq = f"{marker}:{name}"                 # synthetic identity for name-only imports
            r = by_seq.get((marker, seq))
            if r is None:
                r = ReferenceAllele(project_id=project_id, marker=marker, sequence=seq,
                                    allele_name=name)
                db.add(r); db.flush()
                by_seq[(marker, seq)] = r
            by_name[(marker, name)] = r
        return r.id

    return resolve


def _pop_study_resolver(db: Session, project_id: int):
    pops = {p.name: p for p in db.scalars(select(Population).where(Population.project_id == project_id))}
    studies = {s.name: s for s in db.scalars(select(Study).where(Study.project_id == project_id))}

    def pop(name):
        name = (name or "").strip()
        if not name:
            return None
        if name not in pops:
            p = Population(project_id=project_id, name=name); db.add(p); db.flush(); pops[name] = p
        return pops[name].id

    def study(name, population_id=None):
        name = (name or "").strip()
        if not name:
            return None
        if name not in studies:
            s = Study(project_id=project_id, name=name, population_id=population_id)
            db.add(s); db.flush(); studies[name] = s
        return studies[name].id

    return pop, study


# ----------------------------- imports -----------------------------

def import_genotypes_csv(db: Session, project_id: int, text: str) -> dict:
    """Import samples + consensus from a genotype-matrix CSV (columns `<marker>_1`/`<marker>_2`).
    Imported samples are treated as curated (genotype_ok=True); alleles align/synthesise by name."""
    reader = csv.DictReader(io.StringIO(text))
    cols = reader.fieldnames or []
    markers = sorted({c[:-2] for c in cols if c.endswith("_1")}
                     & {c[:-2] for c in cols if c.endswith("_2")})
    if not markers:
        raise ValueError("no marker columns found — expected `<marker>_1` and `<marker>_2` pairs")
    name_col = "name" if "name" in cols else ("sample" if "sample" in cols else None)
    if name_col is None:
        raise ValueError("missing a `name` (or `sample`) column")

    alle = _allele_resolver(db, project_id)
    pop, study = _pop_study_resolver(db, project_id)
    n_samples = n_cons = 0
    ids: list = []
    for row in reader:
        name = (row.get(name_col) or "").strip()
        if not name:
            continue
        pid = pop(row.get("population"))
        s = Sample(public_id=uuid.uuid4().hex, system_code="", project_id=project_id,
                   population_id=pid, study_id=study(row.get("study"), pid),
                   name=name, genotype_ok=True)
        db.add(s); db.flush(); s.system_code = f"S-{s.id:06d}"
        n_samples += 1; ids.append(s.id)
        for m in markers:
            a1 = (row.get(f"{m}_1") or "").strip() or None
            a2 = (row.get(f"{m}_2") or "").strip() or None
            if not a1 and not a2:
                continue
            db.add(ConsensusGenotype(
                sample_id=s.id, marker=m, source=ConsensusSource.manual,
                allele1=a1, allele1_id=alle(m, a1), allele2=a2, allele2_id=alle(m, a2)))
            n_cons += 1
    db.flush()
    return {"samples": n_samples, "consensus": n_cons, "markers": len(markers)}


def import_project_json(db: Session, owner_id: int, data: dict) -> Project:
    """Create a NEW project from a project-JSON export (round-trip; preserves allele sequences)."""
    pj = data.get("project", {})
    name = base = pj.get("name") or "Imported project"
    k = 1
    while db.scalar(select(Project.id).where(Project.owner_user_id == owner_id, Project.name == name)):
        k += 1; name = f"{base} ({k})"
    project = Project(public_id=uuid.uuid4().hex, name=name, organisation=pj.get("organisation"),
                      description=pj.get("description"), owner_user_id=owner_id)
    db.add(project); db.flush()

    pop_id: dict = {}
    for p in data.get("populations", []):
        row = Population(project_id=project.id, name=p["name"],
                         description=p.get("description"))
        db.add(row); db.flush(); pop_id[p["name"]] = row.id
    study_id: dict = {}
    for s in data.get("studies", []):
        row = Study(project_id=project.id, name=s["name"],
                    population_id=pop_id.get(s.get("population")),
                    include_in_matching=s.get("include_in_matching", True))
        db.add(row); db.flush(); study_id[s["name"]] = row.id
    for r in data.get("reference_alleles", []):
        db.add(ReferenceAllele(project_id=project.id, marker=r["marker"], sequence=r["sequence"],
                               length=r.get("length"), variant=r.get("variant"),
                               allele_name=r["allele_name"], n=r.get("n")))
    db.flush()
    alle = _allele_resolver(db, project.id)

    animals: dict = defaultdict(list)
    for sd in data.get("samples", []):
        s = Sample(
            public_id=uuid.uuid4().hex, system_code="", project_id=project.id,
            population_id=pop_id.get(sd.get("population")), study_id=study_id.get(sd.get("study")),
            name=sd["name"], sex=Sex(sd.get("sex", "unknown")),
            sex_locked=sd.get("sex_locked", False), discard_sample=sd.get("discard_sample", False),
            is_animal_reference=sd.get("is_animal_reference", False),
            genotype_ok=sd.get("genotype_ok", False))
        db.add(s); db.flush(); s.system_code = f"S-{s.id:06d}"
        for cg in sd.get("consensus", []):
            db.add(ConsensusGenotype(
                sample_id=s.id, marker=cg["marker"], source=ConsensusSource.manual,
                allele1=cg.get("allele1"),
                allele1_id=alle(cg["marker"], cg.get("allele1"), cg.get("allele1_seq")),
                allele2=cg.get("allele2"),
                allele2_id=alle(cg["marker"], cg.get("allele2"), cg.get("allele2_seq")),
                quality_index=cg.get("quality_index"), success_rate=cg.get("success_rate"),
                n_amp=cg.get("n_amp"), ado=cg.get("ado")))
        if sd.get("animal") and sd.get("population") in pop_id:
            animals[(sd["population"], sd["animal"])].append(s)
    db.flush()

    for (popname, label), members in animals.items():   # recreate animals (rerun matching to refine)
        sg = MatchSubgroup(public_id=uuid.uuid4().hex, population_id=pop_id[popname], label=label,
                           reference_sample_id=members[0].id, n_samples=len(members))
        db.add(sg); db.flush()
        for m in members:
            m.subgroup_id = sg.id
    db.flush()
    return project


def _name_for(name, seq):
    """Allele display name: the given name, else a length-derived name (pipeline convention)."""
    if name:
        return name
    return str(len(seq)) if seq else None


def import_genotypes_long_csv(db: Session, project_id: int, text: str) -> dict:
    """Long-format import: one row per sample x marker, with optional allele SEQUENCE columns.

    Columns: sample (or name), marker, allele1 [, allele1_seq, allele2, allele2_seq, population,
    study]. When a sequence is given, the allele gets a true sequence-level identity (matchable
    across sources); otherwise it falls back to name-based identity.
    """
    reader = csv.DictReader(io.StringIO(text))
    cols = set(reader.fieldnames or [])
    sample_col = "sample" if "sample" in cols else ("name" if "name" in cols else None)
    if sample_col is None or "marker" not in cols or "allele1" not in cols:
        raise ValueError("long CSV needs columns: sample (or name), marker, allele1 "
                         "[, allele1_seq, allele2, allele2_seq, population, study]")
    alle = _allele_resolver(db, project_id)
    pop, study = _pop_study_resolver(db, project_id)
    samples: dict = {}
    markers: set = set()
    n_cons = 0
    for row in reader:
        name = (row.get(sample_col) or "").strip()
        marker = (row.get("marker") or "").strip()
        if not name or not marker:
            continue
        s = samples.get(name)
        if s is None:
            pid = pop(row.get("population"))
            s = Sample(public_id=uuid.uuid4().hex, system_code="", project_id=project_id,
                       population_id=pid, study_id=study(row.get("study"), pid),
                       name=name, genotype_ok=True)
            db.add(s); db.flush(); s.system_code = f"S-{s.id:06d}"; samples[name] = s
        a1 = (row.get("allele1") or "").strip() or None
        a2 = (row.get("allele2") or "").strip() or None
        s1 = (row.get("allele1_seq") or "").strip() or None
        s2 = (row.get("allele2_seq") or "").strip() or None
        n1, n2 = _name_for(a1, s1), _name_for(a2, s2)
        if n1 is None and n2 is None:
            continue
        markers.add(marker)
        db.add(ConsensusGenotype(
            sample_id=s.id, marker=marker, source=ConsensusSource.manual,
            allele1=n1, allele1_id=alle(marker, n1, s1) if n1 else None,
            allele2=n2, allele2_id=alle(marker, n2, s2) if n2 else None))
        n_cons += 1
    db.flush()
    return {"samples": len(samples), "consensus": n_cons, "markers": len(markers)}


def import_genotypes(db: Session, project_id: int, text: str) -> dict:
    """Dispatch: a `marker` column -> long format (with sequences); else the wide matrix."""
    header = next(csv.reader(io.StringIO(text)), [])
    if "marker" in {c.strip() for c in header}:
        return import_genotypes_long_csv(db, project_id, text)
    return import_genotypes_csv(db, project_id, text)
