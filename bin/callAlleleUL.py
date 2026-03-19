#!/usr/bin/env python3
# for testing only#!/Users/elena/miniconda3/envs/ngs_pipelines/bin/python

import argparse
import pandas as pd
import os
import re


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
        name, seq = item.split(":")
        seq = seq.strip()
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

    parser.add_argument("--kit_id")
    parser.add_argument("--sample_count")
    parser.add_argument("--sequence_data")
    parser.add_argument("--locus_name")
    parser.add_argument("--locus_type")
    parser.add_argument("--locus_sequence")
    parser.add_argument("--progressive_threshold", default=True)
    parser.add_argument("--alleles_only", default=True)
    parser.add_argument("--parameters_file_path", default="/usr/local/bin/parameters.json")
    parser.add_argument("--ngsfilter_path")
    

    args = parser.parse_args()

    with open(args.parameters_file_path, "r") as f:
        data = f.read()
        f.close()

    parameters = eval(data)
    
    counts = pd.read_csv(args.sample_count)
    sequences = pd.read_csv(args.sequence_data)
    
    # format inputs
    reads = pd.melt(counts, id_vars="id", var_name="Sequence_id", value_name="Read_Count") # Convert to long format
    reads = reads.merge(sequences, left_on="Sequence_id", right_on="id").drop(columns=["id_y", "Sequence_id" ])
    reads.rename(columns={"id_x": "Sample_Name"}, inplace=True)
    reads["length"] = reads["sequence"].apply(len)
    #filter reads and set up thresholds
    reads = reads[reads["Read_Count"] > parameters["discard_threshold"]]
    if args.progressive_threshold:
        if len(reads[reads["Sample_Name"].str.contains(parameters["negative_name"])]["Read_Count"]) != 0:
            # L = 1.5 * int(max(gen[gen["Sample_Name"].str.contains("^B[0-9]{2}")]["Read_Count"])) #maximum number of reads in one allele in Blanks named B01, B02 etc
            parameters["discard_threshold"] = 1.5 * int(max(reads[reads["Sample_Name"].str.contains(parameters["negative_name"])]["Read_Count"]))    # Mark as Low count alleles, that have 1.5 * number of reads in max Blank
            reads = reads[reads["Read_Count"] > parameters["discard_threshold"]]  # Filter out samples with number of reads < or equal to progressive threshold
            parameters["str_low_allele_flag_threshold"] = reads["Read_Count"].quantile(0.05)  # allele marked as low if it is the bottom 5% of distribution
            parameters["snp_low_allele_flag_threshold"] = reads["Read_Count"].quantile(0.05)  # allele marked as low if it is the bottom 5% of distribution
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
            print(f"Unknown locus type: {args.locus_type}. Must be either 'microsat' or 'snp'")
            exit()
        genotypes.append(alleles)

    all_geno = pd.concat(genotypes)
    # If clean == TRUE, return only sequences which were tagged as allele or stutter
    if args.alleles_only:
        all_geno = all_geno[all_geno["stutter"] | all_geno["called"]]
    # format for the database
    ngsfilter = pd.read_csv(args.ngsfilter_path)
    ngsfilter = ngsfilter[["sample","sample_tag"]]
    ngsfilter = ngsfilter.rename(columns={"sample_tag":"TagCombo"})
    ngsfilter = ngsfilter.drop_duplicates(subset="sample")
    all_geno = pd.merge(all_geno, ngsfilter,left_on="Sample_Name", right_on="sample", how='left')


    all_geno["Plate"] = all_geno["Sample_Name"].apply(lambda row: row.split("__")[-1]).str.replace("PP", "")
    all_geno["Position"] = all_geno["Sample_Name"].apply(lambda row: row.split("__")[-2]).astype(int)
    all_geno["Sample_Name"] = all_geno["Sample_Name"].apply(lambda row: row.split("__")[0])
    all_geno["Marker"],all_geno["Run_Name"] = args.locus_name, args.kit_id
    all_geno["called"] = all_geno["called"].astype(str).str.upper()
    all_geno["stutter"] = all_geno["stutter"].astype(str).str.upper()
    all_geno.rename(columns={"sequence": "Sequence"}, inplace=True)

    all_geno = all_geno[["Sample_Name", "Plate", "Read_Count", "Marker", "Run_Name", "length", "Position", "called", "flag", "stutter", "Sequence", "TagCombo"]]
    all_geno.to_csv(f"{args.kit_id}_{args.locus_name}_genotypes.txt", sep="\t", index=False)


    frequency = (all_geno.groupby(["Marker", "Sequence"], as_index=False)["Read_Count"].sum().rename(columns={"Read_Count": "N"}).sort_values(["Marker", "N"], ascending=[True, False]))
    frequency = frequency[["Marker", "N", "Sequence"]]
    frequency.to_csv(f"{args.kit_id}_{args.locus_name}_frequency_of_sequences_by_marker.txt", sep="\t", index=False)


    positions = ngsfilter.copy()
    positions["Plate"] = positions["sample"].apply(lambda row: row.split("__")[-1]).str.replace("PP", "")
    positions["Position"] = positions["sample"].apply(lambda row: row.split("__")[-2]).astype(int)
    positions["Sample_Name"] = positions["sample"].apply(lambda row: row.split("__")[0])
    positions["Read_Count"], positions["length"] = "", ""
    positions["Marker"],positions["Run_Name"] = locus_name, kit_id
    positions = positions[["Sample_Name", "Plate", "Read_Count", "Marker", "Run_Name", "length", "Position", "TagCombo"]]
    positions.to_csv(f"{args.kit_id}_{args.locus_name}_positions.txt", sep="\t", index=False)

if __name__ == "__main__":
    main()