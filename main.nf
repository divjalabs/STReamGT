#!/usr/bin/env nextflow


// Set up parameters for the run

params.input = "input.tsv"
params.min_identity = 0.9
params.min_overlap = 20


// Import modules
include {  MAKE_NGSFILTER  } from './modules/make_ngsfilter'
include {  MERGE_NGSFILTER  } from './modules/make_ngsfilter'
include { PAIR_FILTER } from './modules/pair_filter'
include { DEMULTIPLEX_READS } from './modules/demultiplex_reads'
include { PROCESS_LOCI } from './modules/process_loci'

// Load sample sheet

samples_ch = Channel
    .fromPath(params.input)
    .splitCsv(header:true, sep:'\t')

// Data for ngsfilter

ngsfilter_input_ch = samples_ch.map { row ->
    tuple(
        row.kit_id,
        file(row.sample_path),
        row.tags,
        file(row.tags_path),
        file(row.primers_path)
    )
}

// Reads data
pair_filter_input_ch = samples_ch
    .map { row -> tuple(row.kit_id, file(row.fastq1_path), file(row.fastq2_path)) }
    .take(1) // channel with a single tuple 


primers_input_ch = samples_ch
    .map { row -> file(row.primers_path) }  // get the primers file
    .take(1)                                 // only one species per input.tsv

// the primers have to be just for one species per input.tsv
primers_ch = primers_input_ch
    .splitCsv(header:true)
    .map { row -> tuple(row.locus, row.type, row.sequence) }
    .unique()



/*
Workflow execution
*/
workflow {
    //ngsfilter part
    
    ngsfilter_parts_ch = MAKE_NGSFILTER(ngsfilter_input_ch)
    ngsfilter_files_ch = ngsfilter_parts_ch.collect()
    ngsfilter_files_ch.view()
    kit_id_ch = samples_ch.map { row -> row.kit_id }.first() // extract kit id 
    ngsfilter = MERGE_NGSFILTER(kit_id_ch, ngsfilter_files_ch)
    pair_filter_input_ch.view()

    /* paired_ch = PAIR_FILTER(pair_filter_input_ch)
    demultiplex_ch = DEMULTIPLEX_READS(paired_ch)
    // assigned_reads_file = demultiplex_ch.first()  // assume we have single fastq file at this stage
    loci_reads_ch = primers_ch.combine(demultiplex_ch)
    PROCESS_LOCI(loci_reads_ch) */
}

