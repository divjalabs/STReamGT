#!/usr/bin/env nextflow


// Set up parameters for the run

params.input = "input.tsv"
params.min_identity = 0.9
params.min_overlap = 20

// extract kit_id from TSV
kit_id_val = file(params.input)
    .text
    .readLines()
    .drop(1)            // skip header
    .collect { it.split('\t')[0] }  // kit_id has to be the first column
    .unique()[0]        // kit_id has to be unique





fastq1_path = file(params.input)
    .text
    .readLines()
    .drop(1)            // skip header
    .collect { it.split('\t')[5] }  // kit_id has to be the first column
    .unique()[0]        // kit_id has to be unique

params.kit_id = kit_id_val
println "Using kit_id = ${params.kit_id}"

// Define output structure
params.outdir = "${params.kit_id}"   // top-level folder for this kit, recommended to set up manually
params.inputs_dir = "${params.outdir}/inputs"
params.intermediate_dir = "${params.outdir}/intermediate"
params.results_dir = "${params.outdir}/results"
params.reports_dir = "${params.outdir}/reports"



// Import modules
include {  MAKE_NGSFILTER  } from './modules/make_ngsfilter'
include {  MERGE_NGSFILTER  } from './modules/make_ngsfilter'
include { PAIR_FILTER } from './modules/pair_filter'
include { DEMULTIPLEX_READS } from './modules/demultiplex_reads'
include { PROCESS_LOCI } from './modules/process_loci'
include { CALL_ALLELES } from './modules/call_alleles'
include { MERGE_ALLELES } from './modules/call_alleles'
include { CONSENSUS } from './modules/call_alleles'
include { CREATE_SUMMARY } from './modules/create_summary'

// Load sample sheet

samples_ch = Channel
    .fromPath(params.input)
    .splitCsv(header:true, sep:'\t')

// Data for ngsfilter
ngsfilter_input_ch = samples_ch.map { row ->
    tuple(
        file(row.sample_path),
        row.tags,
        file(row.tags_path),
        file(row.primers_path)
    )
}

// Reads data
pair_filter_input_ch = samples_ch
    .map { row -> tuple(file(row.fastq1_path), file(row.fastq2_path)) }
    .take(1) // channel with a single tuple 

forward_fastq = samples_ch
    .map { row -> file(row.fastq1_path) }  // only forward read
    .first()                               // only the first sample


// Loci data
primers_input_ch = samples_ch
    .map { row -> file(row.primers_path) }  // get the primers file
    .take(1)                                 // only one species per input.tsv

// the primers have to be just for one species (mulitplex) per input.tsv
primers_ch = primers_input_ch
    .splitCsv(header:true)
    .map { row -> tuple(row.locus, row.type, row.sequence) }
    .unique()

/*
Workflow execution
*/
workflow {

    // saved_inputs = SAVE_INPUTS() // copy inputs to the input directory, need to write module for it 

    ngsfilter_parts_ch = MAKE_NGSFILTER(ngsfilter_input_ch)
    ngsfilter_files_ch = ngsfilter_parts_ch.collect()
    ngsfilter = MERGE_NGSFILTER(ngsfilter_files_ch)
    paired_ch = PAIR_FILTER(pair_filter_input_ch)
    demultiplex_ch = DEMULTIPLEX_READS(paired_ch, ngsfilter)
    loci_reads_ch = primers_ch.combine(demultiplex_ch.assigned_reads)

    loci_ch = PROCESS_LOCI(loci_reads_ch)
    call_alleles_ch = CALL_ALLELES(loci_ch, ngsfilter)
    genotypes_ch = call_alleles_ch.map { gen, freq, pos -> gen }
    freq_ch      = call_alleles_ch.map { gen, freq, pos -> freq }
    pos_ch       = call_alleles_ch.map { gen, freq, pos -> pos }

    genotypes_list = genotypes_ch.collect()
    freq_list      = freq_ch.collect()
    pos_list       = pos_ch.collect()
    merged = MERGE_ALLELES(genotypes_list, freq_list, pos_list)

    // Project-level consensus across replicates (additional output).
    CONSENSUS(merged.genotypes, merged.frequency, merged.positions)
        CREATE_SUMMARY(
        params.kit_id,
        file(fastq1_path),   // raw input FASTQs (wrap in file() so Nextflow stages it as a path)
        paired_ch,              // paired-filtered FASTQs
        demultiplex_ch.assigned_reads,      // reads that passed ngsfilter
        demultiplex_ch.ngsfilter_stats    // stats/errors from demultiplex
    )

    
    //gzip or delete intermediate files 


}

