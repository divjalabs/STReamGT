"""Per-sample consensus genotype plot DATA (rendered client-side, no plotting libs).

Reproduces the pipeline's "fishbone" per marker (make_report.py): X = allele length, Y = read
count, one polyline per PCR replicate (grouped by tag_combo, fallback plate+position), points
flagged red when flag != "". Built entirely from replicate_observations + consensus_genotypes.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReplicateObservation, ConsensusGenotype


def _title(marker: str, cg: ConsensusGenotype | None) -> str:
    if cg is None:
        return marker
    geno = "/".join(a for a in (cg.allele1, cg.allele2) if a)
    return f"{marker}: {geno}" if geno else marker


def sample_plot_data(db: Session, sample_id: int, markers: list[str] | None = None) -> list[dict]:
    obs = db.scalars(
        select(ReplicateObservation).where(
            ReplicateObservation.sample_id == sample_id,
            ReplicateObservation.called.is_(True),
        )
    ).all()
    cons = {c.marker: c for c in db.scalars(
        select(ConsensusGenotype).where(ConsensusGenotype.sample_id == sample_id))}

    by_marker: dict[str, list] = defaultdict(list)
    for o in obs:
        if o.length is not None and o.read_count is not None:
            by_marker[o.marker].append(o)

    wanted = markers if markers else sorted(by_marker)
    out: list[dict] = []
    for marker in wanted:
        rows = by_marker.get(marker, [])
        # one polyline per replicate (tag_combo, else plate|position), sorted by allele length
        groups: dict[str, list] = defaultdict(list)
        for o in rows:
            key = o.tag_combo or f"{o.plate}|{o.position}"
            groups[key].append(o)
        lines = []
        for g in groups.values():
            pts = sorted((o.length, o.read_count) for o in g)
            if pts:
                lines.append([[length, reads] for length, reads in pts])
        points = [
            {"length": o.length, "reads": o.read_count,
             "flagged": bool(o.flag), "stutter": bool(o.stutter), "allele_name": o.allele_name}
            for o in rows
        ]
        out.append({"marker": marker, "title": _title(marker, cons.get(marker)),
                    "lines": lines, "points": points})
    return out
