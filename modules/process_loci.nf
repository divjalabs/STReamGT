process PROCESS_LOCI{

    container 'obitools4_py'

    publishDir { "intermediate" }, mode: 'copy'

    input:
    tuple val(locus), val(type), val(sequence), path(assigned_reads_file)
    
    output:
    path "${locus}.csv"        // only keep the final CSV

    script:
    """
    obigrep -a experiment=${locus} assigned_reads.fastq > ${locus}.fastq
    obiuniq -m sample ${locus}.fastq > ${locus}_uniq.fastq
    obicsv -k experiment -k sample -k count -k obimultiplex_forward_tag -k obimultiplex_reverse_tag  -s ${locus}_uniq.fastq > ${locus}.csv
    """
}