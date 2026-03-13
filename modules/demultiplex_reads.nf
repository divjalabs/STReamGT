process DEMULTIPLEX_READS {

    container 'obitools4_py'

    publishDir params.intermediate_dir, mode: 'symlink'

    input:
    path assembled_reads
    path ngsfilter_file

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