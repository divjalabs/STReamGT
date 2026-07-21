process PAIR_FILTER {

    publishDir params.intermediate_dir, mode: 'symlink'

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

    obigrep -p 'annotations.mode != "join"' --fasta-output \
        aligned_reads.fastq \
        > assembled_reads.fastq
    """
}