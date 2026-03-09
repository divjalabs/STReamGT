#!/usr/bin/env nextflow

params.input = "input.tsv"
params.min_identity = 0.9
params.min_overlap = 20
params.ngsfilter = "/Users/elena/PycharmProjects/ngs_pipelines/DIVJA240/ngsfilters/DIVJA240_ngsfilter.csv"

/*
Import modules
*/
include { PAIR_READS } from './modules/pair_reads'
include { FILTER_ASSEMBLED } from './modules/filter_assembled'
include { DEMULTIPLEX_READS } from './modules/demultiplex_reads'
/*
Load sample sheet
*/
samples_ch = Channel
    .fromPath(params.input)
    .splitCsv(header: true, sep: '\t')
    .map { row ->

        tuple(
            row.kit_id,
            file(row.sample_path),
            row.tags,
            file(row.tags_path),
            file(row.primers_path),
            file(row.fastq1_path),
            file(row.fastq2_path)
        )
    }

/*
Workflow execution
*/
workflow {

    paired_ch = PAIR_READS(samples_ch)
    filtered_ch = FILTER_ASSEMBLED(paired_ch)
    demultiplex_ch = DEMULTIPLEX_READS(filtered_ch, file(params.ngsfilter))
}