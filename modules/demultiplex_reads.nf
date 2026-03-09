process DEMULTIPLEX_READS {

    container 'obitools4'

    publishDir { "intermediate" }, mode: 'symlink'

    input:
    tuple val(kit_id), path(primers_path), path(assembled_reads), path(ngsfilter_file)

    output:
    tuple path("${kit_id}/assigned_reads.fastq"), path(primers_path)

    script:
    """
    obimultiplex \
        -s ${ngsfilter_file} \
        ${assembled_reads} \
        > ${kit_id}/assigned_reads.fastq
    """
}