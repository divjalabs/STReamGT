process FILTER_ASSEMBLED {

    container 'obitools4'

    publishDir { "intermediate/${sample}" }, mode: 'symlink'

    input:
    tuple val(sample), path(aligned_reads)

    output:
    tuple val(sample), path("assembled_reads.fastq")

    script:
    """

    obigrep -p 'annotations.mode != "join"' \
        ${aligned_reads} \
        > assembled_reads.fastq
    """
}