process REPORT {

    tag "${params.kit_id}"
    publishDir params.reports_dir, mode: 'copy', pattern: "*.html"
    publishDir "${params.reports_dir}/logs", mode: 'copy', pattern: "*.log"

    input:
    path reads_summary
    path genotypes
    path positions
    path frequency
    path consensus
    path reference_alleles

    output:
    path("${params.kit_id}_report.html")
    path("${params.kit_id}_consensus_report.html")
    path("${params.kit_id}_report.log")

    script:
    def expected = params.expected_read_number ? "--expected_reads ${params.expected_read_number}" : ""
    """
    make_report.py --kit_id ${params.kit_id} \
        --reads_summary ${reads_summary} \
        --genotypes ${genotypes} \
        --positions ${positions} \
        --frequency ${frequency} \
        --consensus ${consensus} \
        --reference_alleles ${reference_alleles} \
        ${expected}
    """
}
