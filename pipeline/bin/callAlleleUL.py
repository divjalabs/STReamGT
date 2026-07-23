#!/usr/bin/env python3
# for testing only#!/Users/elena/miniconda3/envs/ngs_pipelines/bin/python

import argparse
import json
import logging
import sys
import pandas as pd
import os
import re

# Parameter keys the caller relies on; validated up front so a missing key fails
# with a clear message instead of a KeyError deep inside allele calling.
REQUIRED_PARAMETERS = [
    "discard_threshold", "negative_name",
    "str_stutter_read_proportion", "str_disbalanced_allele_read_proportion",
    "str_low_allele_flag_threshold",
    "snp_low_allele_flag_threshold", "snp_junk_proportion",
    "snp_disbalanced_allele_read_proportion", "snp_divergence_if_not_low",
]

log = logging.getLogger("callAlleleUL")


def setup_logging(log_path):
    """Log to a durable per-locus file AND stderr, so messages survive in the published
    logs and are also captured by Nextflow / the job log. (Explicit config so it works on
    the image's Python 3.10 and older 3.7 alike — no basicConfig(force=...).)"""
    for h in list(log.handlers):
        log.removeHandler(h)
    log.setLevel(logging.INFO)
    log.propagate = False  # keep third-party root INFO (e.g. NumExpr) out of the file
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    for handler in (logging.FileHandler(log_path, mode="w"), logging.StreamHandler(sys.stderr)):
        handler.setFormatter(fmt)
        log.addHandler(handler)


def _die(locus, message):
    """Log a clear, locus-tagged error and abort (non-zero exit)."""
    log.error("locus '%s': %s", locus, message)
    sys.exit(1)


def _as_bool(value):
    """Coerce a CLI flag to bool. argparse passes strings, so '--flag False' must be False,
    not a truthy non-empty string."""
    return str(value).strip().lower() in ("1", "true", "yes", "y", "t")


# Non-positive controls (all of these feed the progressive noise threshold).
NEGATIVE_CONTROL_TYPES = {"sequencing", "pcr", "extraction", "negative"}


def parse_control_type(value):
    """Extract the control_type token from the ngsfilter 6th column.

    Values look like 'type=control;control_type=pcr;' | 'type=sample;' | 'type=NA'.
    Returns the lowercase control type ('pcr', 'sequencing', ...) or '' for samples/NA.
    """
    s = str(value or "")
    if "type=control" not in s:
        return ""
    m = re.search(r"control_type=([^;]+)", s)
    return m.group(1).strip().lower() if m else ""


# Output column layouts (kept in one place so an empty-locus file matches a populated one).
GENOTYPE_COLUMNS = ["Sample_Name", "Plate", "Read_Count", "Marker", "Run_Name",
                    "length", "Position", "called", "flag", "stutter", "Sequence", "TagCombo",
                    "control_type"]
FREQUENCY_COLUMNS = ["Marker", "N", "Sequence"]
POSITION_COLUMNS = ["Sample_Name", "Plate", "Read_Count", "Marker", "Run_Name",
                    "length", "Position", "TagCombo", "control_type"]


def read_csv_or_empty(path):
    """Read a CSV, returning an empty DataFrame if the file has no rows/columns."""
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def positions_from_ngsfilter(ngsfilter_path, locus_name, kit_id):
    """Build the positions table from the ngsfilter alone (independent of read counts)."""
    raw = pd.read_csv(ngsfilter_path)
    cols = ["sample", "sample_tag"] + (["control"] if "control" in raw.columns else [])
    ngsfilter = raw[cols].rename(columns={"sample_tag": "TagCombo"}).drop_duplicates(subset="sample")
    pos = ngsfilter.copy()
    pos["Plate"] = pos["sample"].apply(lambda r: r.split("__")[-1]).str.replace("PP", "")
    pos["Position"] = pos["sample"].apply(lambda r: r.split("__")[-2]).astype(int)
    pos["Sample_Name"] = pos["sample"].apply(lambda r: r.split("__")[0])
    pos["Read_Count"], pos["length"] = "", ""
    pos["Marker"], pos["Run_Name"] = locus_name, kit_id
    pos["control_type"] = pos["control"].apply(parse_control_type) if "control" in pos.columns else ""
    return pos[POSITION_COLUMNS]


def write_empty_locus(args):
    """Emit valid (header-only genotype/frequency + full positions) outputs for a locus
    that had no reads, so one dead locus doesn't fail the whole run (MERGE_ALLELES still works)."""
    pd.DataFrame(columns=GENOTYPE_COLUMNS).to_csv(
        f"{args.kit_id}_{args.locus_name}_genotypes.txt", sep="\t", index=False)
    pd.DataFrame(columns=FREQUENCY_COLUMNS).to_csv(
        f"{args.kit_id}_{args.locus_name}_frequency_of_sequences_by_marker.txt", sep="\t", index=False)
    positions_from_ngsfilter(args.ngsfilter_path, args.locus_name, args.kit_id).to_csv(
        f"{args.kit_id}_{args.locus_name}_positions.txt", sep="\t", index=False)


#STR alele calling
def generate_stutters(seq, motif):
    """Return all unique sequences obtained by removing one motif occurrence."""
    positions = [m.start() for m in re.finditer(motif, seq)]
    stutters = []

    for pos in positions:
        stutter_seq = seq[:pos] + seq[pos + len(motif):]
        stutters.append(stutter_seq)

    # Remove duplicates by converting to set, then back to list
    return list(set(stutters))

def call_alleles_vectorized(alleles, distribution, parameters):
    """
    Vectorized allele calling assuming `alleles['stutter']` has been precomputed.

    Modifies/returns columns: 'called', 'flag', 'stutter_index'
    """
    motif_stutter_prop = parameters["str_stutter_read_proportion"]
    disbalance_prop = parameters["str_disbalanced_allele_read_proportion"]
    low_thr = parameters["str_low_allele_flag_threshold"]

    # Initialize columns
    alleles = alleles.copy()


    # Compute read count proportion
    rh = alleles["Read_Count"] / distribution["max"]

    # --- 1. Alleles with stutter ---
    has_stutter = alleles["hasStutter"]

    # Called if stutter and above threshold
    called_mask = has_stutter & (rh > motif_stutter_prop)
    alleles.loc[called_mask, "called"] = True

    # Flag "D" if disbalanced
    disbalance_mask = called_mask & (rh < disbalance_prop)
    alleles.loc[disbalance_mask, "flag"] += "D"

    # Flag "L" if below low threshold
    low_mask = called_mask & (alleles["Read_Count"] < low_thr)
    alleles.loc[low_mask, "flag"] += "L"

    # --- 2. Alleles with no stutter ---
    no_stutter_mask = ~has_stutter & (alleles["Read_Count"] > distribution["75%"]) # tilda is vectorized version of NOT
    alleles.loc[no_stutter_mask, "called"] = True
    alleles.loc[no_stutter_mask, "flag"] = "N"
    return alleles

#SNP allele calling
def parse_reference_snp(ref_string):
    refs = []

    for item in ref_string.split("/"):
        if ":" not in item:
            raise ValueError(
                f"expected 'name:sequence' pairs separated by '/', got {ref_string!r}")
        name, seq = item.split(":", 1)
        name, seq = name.strip(), seq.strip()
        if not name or not seq:
            raise ValueError(f"empty name or sequence in reference {item!r}")
        refs.append((name, seq, len(seq))) # save to tuple

    return refs

def edit_distance(s1, s2): # light version of Levenshtein distance, returns just score
    if len(s1) < len(s2):
        s1, s2 = s2, s1

    previous = list(range(len(s2) + 1))

    for i, c1 in enumerate(s1):
        current = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous[j + 1] + 1
            deletions = current[j] + 1
            substitutions = previous[j] + (c1 != c2)
            current.append(min(insertions, deletions, substitutions))
        previous = current

    return previous[-1]

def compute_best_reference_scores(sequences, references):

    seq_list = sequences.unique()
    results = {}

    for seq in seq_list:
        best_score = float("inf")
        best_ref = None
        seq_len = len(seq)

        for name, ref_seq, ref_len in references:

            if seq_len == ref_len:
                score = sum(a != b for a, b in zip(seq, ref_seq))
            else:
                score = edit_distance(seq, ref_seq)

            if score < best_score:
                best_score = score
                best_ref = name

        results[seq] = (best_ref, best_score)

    return results

def call_snp_alleles_vectorized(alleles, parameters, max_reads, ref_length):

    alleles["called"] = False
    alleles["flag"] = alleles["flag"].fillna("")

    proportion = alleles["Read_Count"] / max_reads

    # Perfect match
    mask_perfect = alleles["min_score"] == 0
    alleles.loc[mask_perfect, "called"] = True

    # Divergent but allowed
    mask_div = (
        (alleles["min_score"] <= round(ref_length * parameters["snp_divergence_if_not_low"])) &
        (alleles["Read_Count"] > parameters["snp_low_allele_flag_threshold"])
    )

    alleles.loc[mask_div, "called"] = True

    # Disbalanced allele
    mask_dis = (
    (proportion < parameters["snp_disbalanced_allele_read_proportion"]) &
    (alleles["called"]))

    alleles.loc[mask_dis, "flag"] += "D"

    # Junk alleles
    mask_junk = proportion <= parameters["snp_junk_proportion"]
    alleles.loc[mask_junk, "called"] = False

    return alleles

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--kit_id", required=True)
    parser.add_argument("--sample_count", required=True)
    parser.add_argument("--sequence_data", required=True)
    parser.add_argument("--locus_name", required=True)
    parser.add_argument("--locus_type", required=True)
    parser.add_argument("--locus_sequence", required=True)
    parser.add_argument("--progressive_threshold", default=True)
    parser.add_argument("--alleles_only", default=True)
    parser.add_argument("--parameters_file_path", default="/usr/local/bin/parameters.json")
    parser.add_argument("--ngsfilter_path", required=True)


    args = parser.parse_args()
    locus = args.locus_name
    setup_logging(f"{args.kit_id}_{locus}.log")
    log.info("Processing locus %s (%s) for kit %s", locus, args.locus_type, args.kit_id)

    # --- validate inputs up front, with clear messages (fail fast, not deep in pandas) ---
    for label, path in [("--sample_count", args.sample_count),
                        ("--sequence_data", args.sequence_data),
                        ("--ngsfilter_path", args.ngsfilter_path),
                        ("--parameters_file_path", args.parameters_file_path)]:
        if not os.path.isfile(path):
            _die(locus, f"{label} file not found: {path}")

    # ngsfilter must carry the columns both this path and write_empty_locus rely on.
    try:
        ngsfilter_cols = pd.read_csv(args.ngsfilter_path, nrows=0).columns
    except Exception as e:  # noqa: BLE001 — any parse failure is a bad ngsfilter
        _die(locus, f"could not read --ngsfilter_path {args.ngsfilter_path}: {e}")
    for col in ("sample", "sample_tag"):
        if col not in ngsfilter_cols:
            _die(locus, f"--ngsfilter_path has no '{col}' column (columns: {list(ngsfilter_cols)})")

    if args.locus_type not in ("microsat", "snp"):
        _die(locus, f"--locus_type must be 'microsat' or 'snp', got {args.locus_type!r}")
    if not str(args.locus_sequence).strip():
        _die(locus, "--locus_sequence is empty (motif for microsat, references for snp)")
    if args.locus_type == "snp":
        try:
            if not parse_reference_snp(args.locus_sequence):
                _die(locus, "--locus_sequence has no snp references")
        except ValueError as e:
            _die(locus, f"invalid snp --locus_sequence: {e}")

    progressive_threshold = _as_bool(args.progressive_threshold)
    alleles_only = _as_bool(args.alleles_only)

    try:
        with open(args.parameters_file_path) as f:
            parameters = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _die(locus, f"could not read parameters JSON {args.parameters_file_path}: {e}")
    missing = [k for k in REQUIRED_PARAMETERS if k not in parameters]
    if missing:
        _die(locus, f"parameters file is missing keys: {missing}")

    counts = read_csv_or_empty(args.sample_count)
    sequences = read_csv_or_empty(args.sequence_data)

    # A locus with no assigned reads: emit empty outputs and continue rather than crash,
    # so one failed/empty locus doesn't abort the whole run.
    if sequences.empty or counts.empty:
        log.info("No reads for locus %s; writing empty outputs and skipping.", locus)
        write_empty_locus(args)
        return

    # Non-empty files must have the expected schema, or the melt/merge below fails cryptically.
    if "id" not in counts.columns:
        _die(locus, f"--sample_count has no 'id' column (columns: {list(counts.columns)})")
    for col in ("id", "sequence"):
        if col not in sequences.columns:
            _die(locus, f"--sequence_data has no '{col}' column (columns: {list(sequences.columns)})")

    # format inputs
    reads = pd.melt(counts, id_vars="id", var_name="Sequence_id", value_name="Read_Count") # Convert to long format
    reads = reads.merge(sequences, left_on="Sequence_id", right_on="id").drop(columns=["id_y", "Sequence_id" ])
    reads.rename(columns={"id_x": "Sample_Name"}, inplace=True)
    reads["length"] = reads["sequence"].apply(len)
    # control_type per composite sample name (from the ngsfilter 6th column) — drives the threshold
    # and is carried onto the genotype/position outputs. Empty string for ordinary samples.
    ctrl_ngs = pd.read_csv(args.ngsfilter_path)
    if "control" in ctrl_ngs.columns:
        ctrl_map = (ctrl_ngs[["sample", "control"]].drop_duplicates(subset="sample")
                    .assign(control_type=lambda d: d["control"].apply(parse_control_type))
                    .set_index("sample")["control_type"].to_dict())
    else:
        ctrl_map = {}
    reads["control_type"] = reads["Sample_Name"].map(ctrl_map).fillna("")
    #filter reads and set up thresholds
    reads = reads[reads["Read_Count"] > parameters["discard_threshold"]]
    if progressive_threshold:
        # Negatives = all non-positive controls (sequencing/blank + pcr + extraction). Fall back to
        # the legacy negative_name substring when the ngsfilter has no control column.
        neg_mask = reads["control_type"].isin(NEGATIVE_CONTROL_TYPES)
        if not neg_mask.any():
            neg_mask = reads["Sample_Name"].str.contains(parameters["negative_name"])
        neg_reads = reads[neg_mask]["Read_Count"]
        if len(neg_reads) != 0:
            parameters["discard_threshold"] = 1.5 * int(max(neg_reads))    # 1.5 × max control reads
            reads = reads[reads["Read_Count"] > parameters["discard_threshold"]]  # drop noise floor
            parameters["str_low_allele_flag_threshold"] = reads["Read_Count"].quantile(0.05)  # bottom 5%
            parameters["snp_low_allele_flag_threshold"] = reads["Read_Count"].quantile(0.05)  # bottom 5%
    genotypes = []
    for sample_name, data in reads.groupby(["Sample_Name"]):
        data = data.reset_index(drop=True)
        alleles = data.copy()  # Create output dataframe
        alleles["called"], alleles["flag"], alleles["stutter"] = False, "", False  # Create columns with genotype
        alleles.sort_values(by="Read_Count", inplace=True, ascending=False)
        distribution = alleles["Read_Count"].describe()  # maximum allele count

        if args.locus_type == "microsat":
            motif = (str(args.locus_sequence).lower())
            alleles = alleles[alleles["sequence"].str.contains(motif+motif, regex=False)] # Keep only lines with two repeated motifs

            # mark all the stutters without loop
            alleles["candidate_stutters"] = alleles["sequence"].apply(lambda s: generate_stutters(s, motif))
            exploded = alleles.explode("candidate_stutters") # takes into account possibility of multiple stutters
            seq_to_index = alleles.reset_index().set_index("sequence")["index"]
            exploded["stutter_index"] = exploded["candidate_stutters"].map(seq_to_index)
            exploded = exploded.dropna(subset=["stutter_index"])
            alleles.loc[exploded["stutter_index"].astype(int), "stutter"] = True
            alleles["hasStutter"] = alleles.index.isin(exploded.index) # write here if allele has a stutter
            alleles = call_alleles_vectorized(alleles, distribution, parameters) # allele calling
            multiple = (alleles["called"]) & (alleles["flag"] == "")
            if multiple.sum() > 2:
                alleles.loc[multiple, "flag"] += "M"
        elif args.locus_type == "snp":
            reference = parse_reference_snp(args.locus_sequence)
            ref_length = reference[0][2] # assume all the references have the same length
            max_reads = alleles["Read_Count"].max()
            scores = compute_best_reference_scores(alleles["sequence"], reference)
            alleles["best_ref"] = alleles["sequence"].map(lambda s: scores[s][0])
            alleles["min_score"] = alleles["sequence"].map(lambda s: scores[s][1])
            alleles = call_snp_alleles_vectorized(alleles,parameters,max_reads,ref_length) # we can easily add X or Y identification
        else:
            _die(locus, f"unknown locus type: {args.locus_type}")
        genotypes.append(alleles)

    # Everything may have been filtered out (e.g. by a progressive threshold): emit empty outputs
    # rather than crashing on pd.concat([]).
    if not genotypes:
        log.info("No alleles remained for locus %s after filtering; writing empty outputs.", locus)
        write_empty_locus(args)
        return

    all_geno = pd.concat(genotypes)
    # If clean == TRUE, return only sequences which were tagged as allele or stutter
    if alleles_only:
        all_geno = all_geno[all_geno["stutter"] | all_geno["called"]]
    # format for the database (ngsfilter columns were validated up front)
    ngsfilter = pd.read_csv(args.ngsfilter_path)
    keep = ["sample", "sample_tag"] + (["control"] if "control" in ngsfilter.columns else [])
    ngsfilter = ngsfilter[keep]
    ngsfilter = ngsfilter.rename(columns={"sample_tag":"TagCombo"})
    ngsfilter = ngsfilter.drop_duplicates(subset="sample")
    all_geno = all_geno.drop(columns=["control_type"], errors="ignore")  # recompute from ngsfilter below
    all_geno = pd.merge(all_geno, ngsfilter,left_on="Sample_Name", right_on="sample", how='left')


    all_geno["Plate"] = all_geno["Sample_Name"].apply(lambda row: row.split("__")[-1]).str.replace("PP", "")
    all_geno["Position"] = all_geno["Sample_Name"].apply(lambda row: row.split("__")[-2]).astype(int)
    all_geno["Sample_Name"] = all_geno["Sample_Name"].apply(lambda row: row.split("__")[0])
    all_geno["Marker"],all_geno["Run_Name"] = args.locus_name, args.kit_id
    all_geno["called"] = all_geno["called"].astype(str).str.upper()
    all_geno["stutter"] = all_geno["stutter"].astype(str).str.upper()
    all_geno["control_type"] = all_geno["control"].apply(parse_control_type) if "control" in all_geno.columns else ""
    all_geno.rename(columns={"sequence": "Sequence"}, inplace=True)

    all_geno = all_geno[GENOTYPE_COLUMNS]
    all_geno.to_csv(f"{args.kit_id}_{args.locus_name}_genotypes.txt", sep="\t", index=False)


    frequency = (all_geno.groupby(["Marker", "Sequence"], as_index=False)["Read_Count"].sum().rename(columns={"Read_Count": "N"}).sort_values(["Marker", "N"], ascending=[True, False]))
    frequency = frequency[["Marker", "N", "Sequence"]]
    frequency.to_csv(f"{args.kit_id}_{args.locus_name}_frequency_of_sequences_by_marker.txt", sep="\t", index=False)


    positions = ngsfilter.copy()
    positions["Plate"] = positions["sample"].apply(lambda row: row.split("__")[-1]).str.replace("PP", "")
    positions["Position"] = positions["sample"].apply(lambda row: row.split("__")[-2]).astype(int)
    positions["Sample_Name"] = positions["sample"].apply(lambda row: row.split("__")[0])
    positions["Read_Count"], positions["length"] = "", ""
    positions["Marker"],positions["Run_Name"] = args.locus_name, args.kit_id
    positions["control_type"] = positions["control"].apply(parse_control_type) if "control" in positions.columns else ""
    positions = positions[POSITION_COLUMNS]
    positions.to_csv(f"{args.kit_id}_{args.locus_name}_positions.txt", sep="\t", index=False)
    log.info("Done: wrote genotypes/frequency/positions for locus %s (%d called rows)", locus, len(all_geno))


if __name__ == "__main__":
    main()