"""Pure, testable helpers for the pipeline worker.

Kept free of DB/S3/Celery so they can be unit-tested without infrastructure.
"""
from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass

from app.models.enums import ResultKind

# Map published pipeline output filenames (suffixes) to a ResultKind.
_RESULT_SUFFIXES = {
    "_consensus_genotypes.txt": ResultKind.consensus,  # must win over "_genotypes.txt"
    "_genotypes.txt": ResultKind.genotypes,
    "_positions.txt": ResultKind.positions,
    "_frequency_of_sequences_by_marker.txt": ResultKind.frequency,
    "_reads_summary.csv": ResultKind.reads_summary,
}


def build_nextflow_cmd(
    *, pipeline_dir: str, input_tsv: str, run_dir: str, profile: str,
    min_identity: float, min_overlap: int,
) -> list[str]:
    """Argument vector for `nextflow run`, meant to run with cwd=run_dir.

    We deliberately do NOT pass --outdir: main.nf defaults params.outdir to the kit_id
    and nests results/ + reports/ under it, so outputs land at {run_dir}/{kit_id}/...
    (see collect_results). Runs headless: no ANSI, log inside the run dir.
    """
    return [
        "nextflow", "-log", os.path.join(run_dir, ".nextflow.log"),
        "run", os.path.join(pipeline_dir, "main.nf"),
        "-profile", profile,
        "-ansi-log", "false",
        "--input", input_tsv,
        "--min_identity", str(min_identity),
        "--min_overlap", str(min_overlap),
    ]


def build_render_cmd(*, rmd_path: str, output_html: str, expected_reads: int | None,
                     run_stats: str, alleles: str, positions: str) -> list[str]:
    """Rscript command to render Genotype_stat.Rmd with the job's outputs as params."""
    params = (
        f"expected_read_number={expected_reads if expected_reads is not None else 'NA'},"
        f"run_stats='{run_stats}',alleles='{alleles}',positions='{positions}'"
    )
    r_expr = (
        f"rmarkdown::render('{rmd_path}', output_file='{output_html}', "
        f"params=list({params}), envir=new.env())"
    )
    return ["Rscript", "-e", r_expr]


@dataclass
class CollectedResult:
    kind: ResultKind
    path: str
    filename: str


def collect_results(outdir: str, kit_id: str) -> list[CollectedResult]:
    """Find published outputs under {outdir}/{kit_id}/{results,reports}.

    Mirrors the pipeline's publishDir layout (results_dir / reports_dir).
    """
    found: list[CollectedResult] = []
    for sub in ("results", "reports"):
        d = os.path.join(outdir, kit_id, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            # Longest suffix first so "_consensus_genotypes.txt" beats "_genotypes.txt".
            for suffix, kind in sorted(_RESULT_SUFFIXES.items(), key=lambda kv: -len(kv[0])):
                if name.endswith(suffix):
                    found.append(CollectedResult(kind, os.path.join(d, name), name))
                    break
    return found


def find_result(results: list[CollectedResult], kind: ResultKind) -> str | None:
    for r in results:
        if r.kind == kind:
            return r.path
    return None


def samples_text_to_rows(text: str) -> list[dict]:
    """Parse pasted sample text into TPositionId/SPositionBC rows.

    Accepts CSV/TSV/whitespace with two fields per line: position (e.g. A1) and sample name.
    A header line containing 'position' (any case) is skipped.
    """
    rows: list[dict] = []
    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.replace("\t", ",").split(",") if p.strip()]
        if len(parts) < 2:
            # tolerate whitespace separation
            parts = line.split()
        if len(parts) < 2:
            raise ValueError(f"cannot parse sample line: {raw!r} (need position and name)")
        pos, name = parts[0], parts[1]
        if pos.lower() == "tpositionid" or pos.lower() == "position":
            continue
        rows.append({"TPositionId": pos, "SPositionBC": name})
    if not rows:
        raise ValueError("no sample rows parsed from pasted text")
    return rows


def write_sample_xlsx(rows: list[dict], dest_path: str) -> None:
    """Write TPositionId/SPositionBC rows to an .xlsx the pipeline's make_ngsfilter.py reads."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["TPositionId", "SPositionBC"])
    for r in rows:
        ws.append([r["TPositionId"], r["SPositionBC"]])
    wb.save(dest_path)


def sample_rows_to_csv_preview(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["TPositionId", "SPositionBC"])
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()
