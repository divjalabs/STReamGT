#!/usr/bin/env nextflow

params.input = "input.tsv"





process PAIR_READS {

    container 'obitools4'

    input:
    tuple val(sample), path(sample_path), val(tags), path(tags_path), path(primers_path), path(r1), path(r2)

    output:
    tuple val(sample), path("aligned_reads.fastq")

    script:
    """
    mkdir -p work_${sample}

    obipairing \
        -F ${r1} \
        -R ${r2} \
        > aligned_reads.fastq
    """
}



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
}