#!/usr/bin/env nextflow

params.input = "input.tsv"
params.min_identity = 0.9
params.min_overlap = 20


/*
Import modules
*/
include { PAIR_FILTER } from './modules/pair_filter'
include { DEMULTIPLEX_READS } from './modules/demultiplex_reads'
include { PROCESS_LOCI } from './modules/process_loci'
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



// the primers_ch will work only in case of one line in input.csv!!!

primers_ch = samples_ch
    .map { kit_id, sample_path, tags, tags_path, primers_path, r1, r2 ->
        primers_path}
        .splitCsv(header:true)           // parse CSV, automatically ignores header
        .map { row -> row.locus }
        .unique()                               // remove duplicate locus names

/*
Workflow execution
*/
workflow {
    paired_ch = PAIR_FILTER(samples_ch)
    demultiplex_ch = DEMULTIPLEX_READS(paired_ch)
    assigned_reads_file = demultiplex_ch.first()  // assume we have single fastq file at this stage
    PROCESS_LOCI(primers_ch, assigned_reads_file)
}

