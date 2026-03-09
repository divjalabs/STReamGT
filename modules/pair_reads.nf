process PAIR_READS {

    container 'obitools4'

    publishDir { "intermediate/${kit_id}" }, mode: 'symlink'

    input:
    tuple val(kit_id), path(sample_path), val(tags), path(tags_path), path(primers_path), path(r1), path(r2)

    output:
    tuple val(kit_id), path("${kit_id}/aligned_reads.fastq")

    script:
    """
    mkdir -p ${kit_id}

    obipairing -F ${r1} -R ${r2} --min-identity ${params.min_identity} --min-overlap ${params.min_overlap} > ${kit_id}/aligned_reads.fastq
    """
}