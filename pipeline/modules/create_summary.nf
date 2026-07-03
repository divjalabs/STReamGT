process CREATE_SUMMARY {
    
    tag "${kit_id}"

    publishDir params.reports_dir, mode: 'copy'

    input:
    val kit_id
    path raw_fastq
    path paired_fastq
    path assigned_fastq
    path ngsfilter_stat

    output:
    path("${kit_id}_reads_summary.csv")


    script:
    """
    #!/bin/bash
    set -euo pipefail

    # count reads in FASTQ
    reads_sequenced=\$(gunzip -c ${raw_fastq} | wc -l)
    reads_sequenced=\$((reads_sequenced / 4))

    reads_paired_filtered=\$(wc -l < ${paired_fastq})
    reads_paired_filtered=\$((reads_paired_filtered / 4))

    reads_pass_ngsfilter=\$(wc -l < ${assigned_fastq})
    reads_pass_ngsfilter=\$((reads_pass_ngsfilter / 4))


    # write CSV
    echo "kit_id,reads_sequenced,reads_paired_filtered,reads_pass_ngsfilter" > ${kit_id}_reads_summary.csv
    echo "${kit_id},\$reads_sequenced,\$reads_paired_filtered,\$reads_pass_ngsfilter" >> ${kit_id}_reads_summary.csv

    """
}