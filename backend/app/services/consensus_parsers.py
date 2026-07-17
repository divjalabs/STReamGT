"""Pure parsers for the pipeline's tab-separated output tables.

No DB/S3 dependencies so they can be unit-tested in isolation (like worker/pipeline_run.py).
Column names mirror pipeline/bin/callConsensus.py (CONSENSUS_COLUMNS / REFERENCE_COLUMNS) and
callAlleleUL.py (GENOTYPE_COLUMNS / POSITION_COLUMNS). Header-only (empty) files -> [].
"""
from __future__ import annotations

import csv
from dataclasses import dataclass


def _s(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


def _i(v: str | None) -> int | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return int(float(v))  # tolerate "3.0"
    except ValueError:
        return None


def _f(v: str | None) -> float | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _b(v: str | None) -> bool:
    return (v or "").strip().upper() == "TRUE"


def _rows(text: str) -> list[dict]:
    reader = csv.DictReader(text.splitlines(), delimiter="\t")
    return [r for r in reader]


@dataclass
class ConsensusRow:
    sample_name: str
    marker: str
    allele1: str | None
    allele2: str | None
    allele3: str | None
    allele4: str | None
    ncnf_a1: int | None
    ncnf_a2: int | None
    confirmed_alleles: str
    unconfirmed_alleles: str
    n_amp: int | None
    n_amp_ok: int | None
    success_rate: float | None
    ado: int | None
    ado_rate: float | None
    quality_index: float | None
    false_alleles: int | None
    reads_per_amp: int | None
    sd_reads_per_amp: float | None


@dataclass
class RefAlleleRow:
    marker: str
    sequence: str
    length: int | None
    variant: int | None
    allele_name: str
    n: int | None


@dataclass
class GenotypeRow:
    sample_name: str
    plate: str | None
    read_count: int | None
    marker: str
    run_name: str | None
    length: int | None
    position: int | None
    called: bool
    flag: str
    stutter: bool
    sequence: str | None
    tag_combo: str | None


@dataclass
class PositionRow:
    sample_name: str
    plate: str | None
    marker: str
    run_name: str | None
    position: int | None
    tag_combo: str | None


def parse_consensus(text: str) -> list[ConsensusRow]:
    out: list[ConsensusRow] = []
    for r in _rows(text):
        if not _s(r.get("Sample")):
            continue
        out.append(ConsensusRow(
            sample_name=r["Sample"].strip(),
            marker=(r.get("Mrkr") or "").strip(),
            allele1=_s(r.get("Al1")), allele2=_s(r.get("Al2")),
            allele3=_s(r.get("Al3")), allele4=_s(r.get("Al4")),
            ncnf_a1=_i(r.get("NcnfA1")), ncnf_a2=_i(r.get("NCnfA2")),
            confirmed_alleles=(r.get("ConfirmedAlleles") or "").strip(),
            unconfirmed_alleles=(r.get("UnconfirmedAlleles") or "").strip(),
            n_amp=_i(r.get("NAmp")), n_amp_ok=_i(r.get("NAmpOK")),
            success_rate=_f(r.get("Success")),
            ado=_i(r.get("ADO")), ado_rate=_f(r.get("ADORate")),
            quality_index=_f(r.get("QualityIndex")),
            false_alleles=_i(r.get("FalseAlleles")),
            reads_per_amp=_i(r.get("ReadsPerAmp")),
            sd_reads_per_amp=_f(r.get("SD_ReadsPerAmp")),
        ))
    return out


def parse_reference_alleles(text: str) -> list[RefAlleleRow]:
    out: list[RefAlleleRow] = []
    for r in _rows(text):
        seq = _s(r.get("Sequence"))
        if not seq:
            continue
        out.append(RefAlleleRow(
            marker=(r.get("Marker") or "").strip(),
            sequence=seq,
            length=_i(r.get("Length")),
            variant=_i(r.get("Variant")),
            allele_name=(r.get("AlleleName") or "").strip(),
            n=_i(r.get("N")),
        ))
    return out


def parse_genotypes(text: str, *, called_only: bool = True) -> list[GenotypeRow]:
    out: list[GenotypeRow] = []
    for r in _rows(text):
        if not _s(r.get("Sample_Name")):
            continue
        called = _b(r.get("called"))
        if called_only and not called:
            continue
        out.append(GenotypeRow(
            sample_name=r["Sample_Name"].strip(),
            plate=_s(r.get("Plate")),
            read_count=_i(r.get("Read_Count")),
            marker=(r.get("Marker") or "").strip(),
            run_name=_s(r.get("Run_Name")),
            length=_i(r.get("length")),
            position=_i(r.get("Position")),
            called=called,
            flag=(r.get("flag") or "").strip(),
            stutter=_b(r.get("stutter")),
            sequence=_s(r.get("Sequence")),
            tag_combo=_s(r.get("TagCombo")),
        ))
    return out


def parse_positions(text: str) -> list[PositionRow]:
    out: list[PositionRow] = []
    for r in _rows(text):
        if not _s(r.get("Sample_Name")):
            continue
        out.append(PositionRow(
            sample_name=r["Sample_Name"].strip(),
            plate=_s(r.get("Plate")),
            marker=(r.get("Marker") or "").strip(),
            run_name=_s(r.get("Run_Name")),
            position=_i(r.get("Position")),
            tag_combo=_s(r.get("TagCombo")),
        ))
    return out
