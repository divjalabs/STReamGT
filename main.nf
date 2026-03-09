#!/usr/bin/env nextflow

params.input = "input.tsv"
params.min_identity = 0.9
params.min_overlap = 20
params.ngsfilter = "/Users/elena/PycharmProjects/ngs_pipelines/DIVJA240/ngsfilters/DIVJA240_ngsfilter.csv"

/*
Import modules
*/
include { MAKE_NGSFILTER } from './modules/make_ngsfilter'
include { PAIR_FILTER } from './modules/pair_filter'
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
    ngsfilter_ch = MAKE_NGSFILTER(samples_ch)
    paired_ch = PAIR_FILTER(samples_ch)
    demultiplex_input_ch = paired_ch.map { paired ->
        def kit_id = paired[0]
        def primers_path = paired[1]
        def assembled_reads = paired[2]
        
        // get the first (and only) element from ngsfilter_ch
        ngsfilter_ch.first().map { ngsfilter_file ->
            tuple(kit_id, primers_path, assembled_reads, ngsfilter_file)
        }
}.flatten()

    DEMULTIPLEX_READS(demultiplex_input_ch)
}