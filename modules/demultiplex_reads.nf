process DEMULTIPLEX_READS {

    container 'obitools4_py'

    publishDir { "intermediate/${kit_id}" }, mode: 'symlink'

    input:
    tuple val(kit_id), path(assembled_reads), path(ngsfilter_file)

    output:
    path("assigned_reads.fastq")

    script:
    """
    obimultiplex \
        -s ${ngsfilter_file} \
        ${assembled_reads} \
        > assigned_reads.fastq
    """
}