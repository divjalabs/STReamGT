#!/usr/bin/env python3
"""Project-level consensus step.

Runs after MERGE_ALLELES on the whole-kit outputs. Two stages:
  1. reference-allele naming  -> {kit_id}_reference_alleles.txt
  2. consensus per Sample x Marker across replicates -> {kit_id}_consensus_genotypes.txt

Adapted and cleaned from the monolithic callAllelegit.py (lines ~315-415): vectorized allele
naming + replicate counting, no deprecated DataFrame.append, divide-by-zero guards, single-kit
(no tab_dirs loop), no R graphing.
"""
import argparse
import json
from collections import Counter

import pandas as pd

# Output column layout (kept identical to the original for downstream / R compatibility).
CONSENSUS_COLUMNS = [
    "Sample", "Mrkr", "Al1", "Al2", "Al3", "Al4", "NcnfA1", "NCnfA2",
    "ConfirmedAlleles", "UnconfirmedAlleles", "NAmp", "NAmpOK", "Success",
    "ADO", "ADORate", "QualityIndex",
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


def replicate_counts(positions):
    """NAmp = number of replicate plates per (Sample_Name, Marker), from the positions table."""
    if positions.empty:
        return pd.DataFrame(columns=["Sample_Name", "Marker", "NAmp"])
    return (positions.groupby(["Sample_Name", "Marker"])["Plate"]
            .nunique().reset_index().rename(columns={"Plate": "NAmp"}))


def consensus_for_group(sample, marker, group, namp, thr_homo, thr_hetero):
    """Compute one consensus row for a single (Sample, Marker) group of called alleles."""
    counts = Counter(group["AlleleName"])
    # Most frequent first (by count), then shorter/earlier allele name.
    counts = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    threshold = thr_hetero if len(counts) > 1 else thr_homo

    unconfirmed, confirmed, consensus = [], {}, []
    for allele in counts:
        rows = group[group["AlleleName"] == allele]
        n_unflagged = int((rows["flag"] == "").sum())
        n_flagged = int((rows["flag"] != "").sum())
        if n_unflagged == 0:                         # every replicate flagged -> unconfirmed
            unconfirmed.append(allele)
            continue
        if n_flagged > 0:                            # flagged AND clean replicates -> confirmed-but-flagged
            confirmed[allele] = n_flagged            # record how many replicates were flagged
        (consensus if len(rows) > threshold else unconfirmed).append(allele)

    # Amplification success / allelic dropout metrics.
    if len(consensus) == 2:
        ado = abs(counts[consensus[0]] - counts[consensus[1]])
        namp_ok = namp - ado
    elif len(consensus) == 1:
        ado = 0
        namp_ok = counts[consensus[0]]
    else:
        ado = 0
        namp_ok = 0
    ado_rate = ado / namp_ok if namp_ok else 0
    quality_index = namp_ok / namp if namp else 0
    success = quality_index * 100

    consensus = (consensus + ["", "", "", ""])[:4]   # pad to Al1..Al4
    ncnf1 = confirmed.get(consensus[0], "") if consensus[0] else ""
    ncnf2 = confirmed.get(consensus[1], "") if consensus[1] else ""

    return {
        "Sample": sample, "Mrkr": marker,
        "Al1": consensus[0], "Al2": consensus[1], "Al3": consensus[2], "Al4": consensus[3],
        "NcnfA1": ncnf1, "NCnfA2": ncnf2,
        "ConfirmedAlleles": ";".join(confirmed.keys()),
        "UnconfirmedAlleles": ";".join(unconfirmed),
        "NAmp": namp, "NAmpOK": namp_ok, "Success": success,
        "ADO": ado, "ADORate": ado_rate, "QualityIndex": quality_index,
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
        print("No genotypes/frequency; wrote empty consensus + reference outputs.")
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
    print(f"Wrote {len(rows)} consensus rows to {consensus_out}")


if __name__ == "__main__":
    main()
