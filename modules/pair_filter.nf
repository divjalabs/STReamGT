process PAIR_FILTER {

    container 'obitools4_py'

    publishDir params.intermediate_dir, mode: 'copy'

    input:
    tuple path(r1), path(r2)

    output:
    path("assembled_reads.fastq")

    script:
    """

    obipairing -F ${r1} -R ${r2} \
        --min-identity ${params.min_identity} \
        --min-overlap ${params.min_overlap} \
        > aligned_reads.fastq

    obigrep -p 'annotations.mode != "join"' \
        aligned_reads.fastq \
        > assembled_reads.fastq
    """
}