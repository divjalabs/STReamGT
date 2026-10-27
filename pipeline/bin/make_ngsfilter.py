#!/usr/bin/env python3

# use for testing only! /Users/elena/miniconda3/envs/ngs_pipelines/bin/python

# input columns: kit_id	sample_path	tags	tags_path	primers_path
#output columns: experiment	sample	sample_tag	forward_primer	reverse_primer	control, where sample name is HRM16C__1__PP1
# the 6th "control" column encodes: type=control;control_type=pcr;  |  type=sample;  |  type=NA

import argparse
import pandas as pd
#import os
import re

# function to parse tag combo sets
def parse_tags(tag_string):
    tags = []
    parts = [p.strip() for p in tag_string.split(',')]

    for part in parts:

        if '-' in part:
            start, end = part.split('-')

            start_num = int(re.findall(r'\d+', start)[0])
            end_num = int(re.findall(r'\d+', end)[0])

            tags.extend([f"PP{i}" for i in range(start_num, end_num + 1)])

        else:
            tags.append(part)

    return tags

# change positions from letter_number to number
def plate_to_number(pos):
    pos = pos.strip().upper()

    row = pos[0]
    col = int(pos[1:])

    row_map = {letter: i for i, letter in enumerate("ABCDEFGH")}

    return row_map[row] + 1 + (col - 1) * 8

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--kit_id")
    parser.add_argument("--tags")
    parser.add_argument("--sample_path")
    parser.add_argument("--tags_path")
    parser.add_argument("--primers_path")

    args = parser.parse_args()
    
    primers = pd.read_csv(args.primers_path).reset_index(drop=True)  # read file with primers
    primers = primers[["locus", "primerF", "primerR"]]
    primers.drop_duplicates(inplace=True)
    
    tagcombo = pd.read_csv(args.tags_path) # read file with tags
    tags = parse_tags(args.tags)
    tags.append("Position")
    tagcombo = tagcombo[tags] # select tagscombo
    tagcombo_long = tagcombo.melt(id_vars = "Position", var_name="plate", value_name="tags") # transform to the long format
    
    samples = pd.read_excel(args.sample_path)
    # accept friendly column headers from the downloadable plate template
    samples = samples.rename(columns={
        "Position": "TPositionId", "Sample Name": "SPositionBC", "Control type": "control_type",
    })
    samples["Position"] = samples["TPositionId"].apply(plate_to_number)
    samples["Name"] = samples["SPositionBC"].astype(str).str.cat(samples["Position"].astype(str), sep="__")
    # control_type is optional in the sample sheet (empty for ordinary samples)
    if "control_type" not in samples.columns:
        samples["control_type"] = ""
    samples["control_type"] = samples["control_type"].fillna("").astype(str).str.strip()
    samples = samples[["Name", "Position", "control_type"]]

    # Add tagcombo
    samples_tags = tagcombo_long.merge(samples, on="Position", how="left")
    samples_tags["Name"] = samples_tags["Name"].str.cat(samples_tags["plate"].astype(str), sep="__")

    # 6th column: type=control;control_type=X; for control wells, type=sample; for named samples, else NA
    def _control_col(row):
        ct = str(row.get("control_type") or "").strip().lower()
        if ct and ct not in ("sample", "na", "nan"):
            return f"type=control;control_type={ct};"
        if pd.notna(row["Name"]):
            return "type=sample;"
        return "type=NA"
    samples_tags["control"] = samples_tags.apply(_control_col, axis=1)

    # Add primers
    primers["key"] = 1
    samples_tags["key"] = 1
    ngsfilter = primers.merge(samples_tags, on="key").drop(columns="key")
    ngsfilter = ngsfilter[["locus", "Name", "tags", "primerF", "primerR", "control"]]
    ngsfilter.columns = ["experiment",	"sample",	"sample_tag",	"forward_primer",	"reverse_primer",	"control"]


    ngsfilter.to_csv(f"{args.kit_id}_ngsfilter_{args.tags}.csv", index=False)
    
if __name__ == "__main__":
    main()
    