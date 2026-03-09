process PAIR_FILTER {

    container 'obitools4'

    publishDir { "intermediate/${kit_id}" }, mode: 'symlink'

    input:
    tuple val(kit_id), path(sample_path), val(tags), path(tags_path), path(primers_path), path(r1), path(r2)

    output:
    tuple val(kit_id), path(primers_path), path("${kit_id}/assembled_reads.fastq")

    script:
    """
    mkdir -p ${kit_id}

    obipairing -F ${r1} -R ${r2} \
        --min-identity ${params.min_identity} \
        --min-overlap ${params.min_overlap} \
        > ${kit_id}/aligned_reads.fastq

    obigrep -p 'annotations.mode != "join"' \
        ${kit_id}/aligned_reads.fastq \
        > ${kit_id}/assembled_reads.fastq
    """
}