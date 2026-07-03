"""Build the pipeline's input.tsv from a job's kit + sample batches.

The Nextflow pipeline consumes a TAB-separated samplesheet with header:

    kit_id  sample_path  tags  tags_path  primers_path  fastq1_path  fastq2_path

One row per sample batch (amplification plate). All rows in a job share the same
FASTQ pair, tags CSV and primers CSV; only sample_path and the tag selection differ.

`tags` is serialized to match the pipeline's parse_tags() (pipeline/bin/make_ngsfilter.py):
contiguous PP columns collapse to a range like "PP1-PP4"; gaps become comma-separated
groups like "PP1-PP2,PP5".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

HEADER = ["kit_id", "sample_path", "tags", "tags_path", "primers_path", "fastq1_path", "fastq2_path"]


def _pp_num(name: str) -> int:
    m = re.findall(r"\d+", name)
    if not m:
        raise ValueError(f"tag column {name!r} has no numeric suffix")
    return int(m[0])


def serialize_tags(selected: list[str]) -> str:
    """['PP1','PP2','PP3','PP4'] -> 'PP1-PP4'; ['PP1','PP2','PP5'] -> 'PP1-PP2,PP5'."""
    if not selected:
        raise ValueError("a sample batch must select at least one tag column")
    nums = sorted({_pp_num(s) for s in selected})
    groups: list[str] = []
    run_start = run_prev = nums[0]
    for n in nums[1:]:
        if n == run_prev + 1:
            run_prev = n
            continue
        groups.append(_fmt_run(run_start, run_prev))
        run_start = run_prev = n
    groups.append(_fmt_run(run_start, run_prev))
    return ",".join(groups)


def _fmt_run(start: int, end: int) -> str:
    return f"PP{start}" if start == end else f"PP{start}-PP{end}"


@dataclass
class BatchRow:
    """A resolved batch: local staged sample sheet path + its selected tag columns."""

    sample_path: str
    selected_tags: list[str]


def build_input_tsv(
    *,
    kit_id: str,
    tags_path: str,
    primers_path: str,
    fastq1_path: str,
    fastq2_path: str,
    batches: list[BatchRow],
) -> str:
    """Render the full input.tsv text. All paths must be local (already staged)."""
    if not batches:
        raise ValueError("at least one sample batch is required")
    lines = ["\t".join(HEADER)]
    for b in batches:
        row = [
            kit_id,
            b.sample_path,
            serialize_tags(b.selected_tags),
            tags_path,
            primers_path,
            fastq1_path,
            fastq2_path,
        ]
        lines.append("\t".join(row))
    return "\n".join(lines) + "\n"
