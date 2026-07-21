process CREATE_SUMMARY {
    
    tag "${kit_id}"

    publishDir params.reports_dir, mode: 'copy'

    input:
    val kit_id
    path raw_fastq
    path paired_fastq
    path assigned_fasta
    path ngsfilter_stat

    output:
    path("${kit_id}_reads_summary.csv"), emit: summary


    script:
    """
    #!/bin/bash
    set -euo pipefail

    # Precise read counts via 'obicount -r' — counts reads (not just sequence records) and is
    # format-agnostic (works on fastq AND fasta / .gz). Output is 2 CSV lines ("entities,n" then
    # "reads,<N>"); take the value on the last line.
    reads_sequenced=\$(obicount -r ${raw_fastq} | tail -n1 | cut -d',' -f2)
    reads_paired_filtered=\$(obicount -r ${paired_fastq} | tail -n1 | cut -d',' -f2)
    reads_pass_ngsfilter=\$(obicount -r ${assigned_fasta} | tail -n1 | cut -d',' -f2)


    # write CSV
    echo "kit_id,reads_sequenced,reads_paired_filtered,reads_pass_ngsfilter" > ${kit_id}_reads_summary.csv
    echo "${kit_id},\$reads_sequenced,\$reads_paired_filtered,\$reads_pass_ngsfilter" >> ${kit_id}_reads_summary.csv

    """
}