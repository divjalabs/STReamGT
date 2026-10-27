#!/usr/bin/env python3
"""Project-level consensus step.

Runs after MERGE_ALLELES on the whole-kit outputs. Two stages:
  1. reference-allele naming  -> {kit_id}_reference_alleles.txt
  2. consensus per Sample x Marker across replicates -> {kit_id}_consensus_genotypes.txt

Adapted and cleaned from the monolithic callAllelegit.py (lines ~315-415): vectorized allele
naming + replicate counting, no deprecated DataFrame.append, divide-by-zero guards, single-kit
(no tab_dirs loop), no R graphing.

Success (SuccessRate), ADO/ADORate and QualityIndex follow the legacy MisBase Access DB
(module mConsensusGenotypes, CreateConsensusTableNGS): they are amplification-based, not
allele-count-based. See docs/consensus-db-vs-pipeline.md.
"""
import argparse
import json
import logging
import sys
from collections import Counter

import pandas as pd

log = logging.getLogger("callConsensus")


def setup_logging(log_path):
    """Log to a durable file AND stderr (published in the pipeline logs + captured by the job log).
    Explicit handler config so it works on Python 3.10 (image) and 3.7 alike."""
    for h in list(log.handlers):
        log.removeHandler(h)
    log.setLevel(logging.INFO)
    log.propagate = False  # keep third-party root INFO (e.g. NumExpr) out of the file
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    for handler in (logging.FileHandler(log_path, mode="w"), logging.StreamHandler(sys.stderr)):
        handler.setFormatter(fmt)
        log.addHandler(handler)

# Output column layout (kept identical to the original for downstream / R compatibility).
CONSENSUS_COLUMNS = [
    "Sample", "Mrkr", "Al1", "Al2", "Al3", "Al4", "NcnfA1", "NCnfA2",
    "ConfirmedAlleles", "UnconfirmedAlleles", "NAmp", "NAmpOK", "Success",
    "ADO", "ADORate", "QualityIndex",
    "FalseAlleles", "ReadsPerAmp", "SD_ReadsPerAmp",
]
REFERENCE_COLUMNS = ["Marker", "Sequence", "Length", "Variant", "AlleleName", "N"]


def read_table_or_empty(path):
    """Read a tab-separated table, returning an empty DataFrame if it has no rows."""
    try:
        return pd.read_csv(path, sep="\t")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def build_reference_alleles(frequency, reference_alleles_path):
    """Name alleles from the frequency table: AlleleName = Length[_Variant] within (Marker, Length).

    Optionally merges an existing reference table (outer) so names stay stable across libraries.
    """
    freq = frequency.copy()
    freq["Length"] = freq["Sequence"].str.len()

    if reference_alleles_path:
        ref = pd.read_csv(reference_alleles_path, sep="\t")
        merged = pd.merge(ref, freq[["Sequence", "Marker", "N"]], on=["Sequence", "Marker"],
                          how="outer", suffixes=("_ref", ""))
        if "N_ref" in merged.columns:  # prefer the fresh N, fall back to the reference's
            merged["N"] = merged["N"].fillna(merged["N_ref"])
            merged = merged.drop(columns=[c for c in ("N_ref",) if c in merged.columns])
        freq = merged
        freq["Length"] = freq["Sequence"].str.len()

    # Shorter alleles and more frequent variants first, then rank variants within (Marker, Length).
    freq = freq.sort_values(["Marker", "Length", "N"], ascending=[True, True, False])
    freq["Variant"] = freq.groupby(["Marker", "Length"]).cumcount() + 1
    freq["AlleleName"] = freq.apply(
        lambda x: f"{x['Length']}_{x['Variant']}" if x["Variant"] > 1 else str(x["Length"]),
        axis=1,
    )
    return freq[REFERENCE_COLUMNS]


AMP_KEYS = ["Plate", "Position"]  # one amplification = one PCR well (DB: Sample x Run x TagCombo)


def replicate_counts(positions):
    """NAmp = number of amplifications attempted per (Sample_Name, Marker).

    Matches the DB's N_Amps: the total number of PCR wells (Plate x Position) the
    sample was run in for that marker, from the positions table. This includes wells
    that produced no called allele (failed amplifications), so it is the correct
    denominator for SuccessRate and QualityIndex."""
    if positions.empty:
        return pd.DataFrame(columns=["Sample_Name", "Marker", "NAmp"])
    keys = [k for k in AMP_KEYS if k in positions.columns] or ["Plate"]
    pos = positions.copy()
    pos["_amp"] = pos[keys].astype(str).agg("|".join, axis=1)
    return (pos.groupby(["Sample_Name", "Marker"])["_amp"]
            .nunique().reset_index().rename(columns={"_amp": "NAmp"}))


def amplification_metrics(group, clean_alleles, genotype_set, is_heterozygous, namp):
    """Amplification-based success / dropout / quality, matching the DB CreateConsensusTableNGS.

    An amplification is one PCR well (Plate x Position). Within a well, an allele is
    *usable* if it is clean (flag == "") or flagged but the same allele is seen clean
    elsewhere at this Sample x Marker (clean_alleles) -- the DB's flag-confirmation rule.

      N_SuccessAmps  amps with >= 1 usable allele
      N_HetAmps      amps with exactly 2 usable alleles
      perfect_amps   amps whose usable-allele set == the consensus genotype
      SuccessRate    100 * N_SuccessAmps / N_Amps
      QualityIndex   perfect_amps / N_Amps
      ADO            (het consensus only) N_SuccessAmps - N_HetAmps; 0 otherwise
      ADO_Rate       ADO / N_SuccessAmps

    ReadsPerAmp / SD_ReadsPerAmp are the mean and SD of total Read_Count per successful
    amplification (over usable-allele rows). The DB's exact formula was not recoverable
    (compressed VBA); this is the faithful reading of the column names/types.
    """
    keys = [k for k in AMP_KEYS if k in group.columns] or ["Plate"]
    has_reads = "Read_Count" in group.columns
    n_success = n_het = n_perfect = 0
    amp_total = 0
    amp_reads = []                                   # total reads of each successful amp's usable alleles
    for _, amp in group.groupby(keys, dropna=False):
        amp_total += 1
        usable_rows = amp[amp["AlleleName"].isin(clean_alleles)]
        usable = set(usable_rows["AlleleName"])
        if not usable:                               # amp produced nothing confirmable
            continue
        n_success += 1
        if has_reads:
            amp_reads.append(float(pd.to_numeric(usable_rows["Read_Count"], errors="coerce").sum()))
        if len(usable) == 2:
            n_het += 1
        if usable == genotype_set:                   # amp reproduced the whole consensus genotype
            n_perfect += 1

    n_amps = max(int(namp), amp_total)               # positions is authoritative; guard vs. inconsistency
    success_rate = 100 * n_success / n_amps if n_amps else 0
    quality_index = n_perfect / n_amps if n_amps else 0
    ado = (n_success - n_het) if is_heterozygous else 0
    ado = max(ado, 0)
    ado_rate = ado / n_success if n_success else 0
    reads = pd.Series(amp_reads, dtype=float)
    reads_per_amp = int(round(reads.mean())) if len(reads) else 0
    sd_reads = round(float(reads.std(ddof=1)), 4) if len(reads) > 1 else 0.0  # sample SD; 0 if <2 amps
    return {"NAmp": n_amps, "NAmpOK": n_success, "Success": success_rate,
            "ADO": ado, "ADORate": ado_rate, "QualityIndex": quality_index,
            "ReadsPerAmp": reads_per_amp, "SD_ReadsPerAmp": sd_reads}


def consensus_for_group(sample, marker, group, namp, thr_homo, thr_hetero):
    """Compute one consensus row for a single (Sample, Marker) group of called alleles."""
    counts = Counter(group["AlleleName"])
    # Most frequent first (by count), then shorter/earlier allele name.
    counts = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    threshold = thr_hetero if len(counts) > 1 else thr_homo

    unconfirmed, confirmed, consensus, clean_alleles = [], {}, [], set()
    for allele in counts:
        rows = group[group["AlleleName"] == allele]
        n_unflagged = int((rows["flag"] == "").sum())
        n_flagged = int((rows["flag"] != "").sum())
        if n_unflagged == 0:                         # every replicate flagged -> unconfirmed
            unconfirmed.append(allele)
            continue
        clean_alleles.add(allele)                    # has a clean copy -> confirms flagged copies in any amp
        if n_flagged > 0:                            # flagged AND clean replicates -> confirmed-but-flagged
            confirmed[allele] = n_flagged            # record how many replicates were flagged
        # DB semantics: threshold = "repeats REQUIRED to accept" (stblSettings.AlleleRepeatsAccept*),
        # so accept at >= threshold (an allele seen `threshold` times is accepted).
        (consensus if len(rows) >= threshold else unconfirmed).append(allele)

    # Amplification-based metrics against the accepted genotype (Al1, Al2); see the DB.
    genotype_set = set(consensus[:2])
    metrics = amplification_metrics(group, clean_alleles, genotype_set,
                                    is_heterozygous=len(consensus) >= 2, namp=namp)

    # FalseAlleles (DB): observation counts of the 3rd-5th most frequent alleles (past the top-2).
    # counts is already ordered most-frequent-first.
    false_alleles = sum(list(counts.values())[2:5])

    consensus = (consensus + ["", "", "", ""])[:4]   # pad to Al1..Al4
    ncnf1 = confirmed.get(consensus[0], "") if consensus[0] else ""
    ncnf2 = confirmed.get(consensus[1], "") if consensus[1] else ""

    return {
        "Sample": sample, "Mrkr": marker,
        "Al1": consensus[0], "Al2": consensus[1], "Al3": consensus[2], "Al4": consensus[3],
        "NcnfA1": ncnf1, "NCnfA2": ncnf2,
        "ConfirmedAlleles": ";".join(confirmed.keys()),
        "UnconfirmedAlleles": ";".join(unconfirmed),
        "FalseAlleles": false_alleles,
        **metrics,
    }


def main():
    parser = argparse.ArgumentParser(description="Build the consensus genotype table.")
    parser.add_argument("--kit_id", required=True)
    parser.add_argument("--genotypes", required=True, help="merged {kit_id}_genotypes.txt")
    parser.add_argument("--frequency", required=True, help="merged frequency table")
    parser.add_argument("--positions", required=True, help="merged positions table")
    parser.add_argument("--parameters_file_path", default="/usr/local/bin/parameters.json")
    parser.add_argument("--reference_alleles", default="", help="optional existing allele names")
    args = parser.parse_args()
    setup_logging(f"{args.kit_id}_consensus.log")
    log.info("Building consensus for kit %s", args.kit_id)

    with open(args.parameters_file_path) as f:
        parameters = json.load(f)
    thr_homo = parameters["AlleleAcceptanceThreshold"]
    thr_hetero = parameters["AlleleAcceptanceThreshold_hetero"]

    genotypes = read_table_or_empty(args.genotypes)
    frequency = read_table_or_empty(args.frequency)
    positions = read_table_or_empty(args.positions)

    consensus_out = f"{args.kit_id}_consensus_genotypes.txt"
    reference_out = f"{args.kit_id}_reference_alleles.txt"

    # Nothing called (empty run / all-empty loci): emit valid header-only outputs and stop.
    if genotypes.empty or frequency.empty:
        pd.DataFrame(columns=REFERENCE_COLUMNS).to_csv(reference_out, sep="\t", index=False)
        pd.DataFrame(columns=CONSENSUS_COLUMNS).to_csv(consensus_out, sep="\t", index=False)
        log.info("No genotypes/frequency; wrote empty consensus + reference outputs.")
        return

    reference = build_reference_alleles(frequency, args.reference_alleles)
    reference.to_csv(reference_out, sep="\t", index=False)

    # Attach allele names, keep called alleles, attach replicate counts.
    called = genotypes[genotypes["called"].astype(str).str.upper() == "TRUE"].copy()
    called["flag"] = called["flag"].fillna("").astype(str).replace("nan", "")
    called = called.merge(reference[["Sequence", "Marker", "AlleleName"]],
                          on=["Sequence", "Marker"], how="left")
    called = called.merge(replicate_counts(positions), on=["Sample_Name", "Marker"], how="left")
    called["NAmp"] = called["NAmp"].fillna(0).astype(int)

    rows = [
        consensus_for_group(sample, marker, group, int(group["NAmp"].iloc[0]), thr_homo, thr_hetero)
        for (sample, marker), group in called.groupby(["Sample_Name", "Marker"])
    ]
    pd.DataFrame(rows, columns=CONSENSUS_COLUMNS).to_csv(consensus_out, sep="\t", index=False)
    log.info("Wrote %d consensus rows to %s", len(rows), consensus_out)


if __name__ == "__main__":
    main()
