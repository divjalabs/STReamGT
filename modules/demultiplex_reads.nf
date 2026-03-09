process DEMULTIPLEX_READS {

    container 'obitools4'

    publishDir { "intermediate/${sample}" }, mode: 'symlink'

    input:
    tuple val(sample), path(assembled_reads)
    path ngsfilter

    output:
    tuple val(sample), path("assigned_reads.fastq")

    script:
    """
    obimultiplex \
        -s ${ngsfilter} ${assembled_reads}  > assigned_reads.fastq
    """
}