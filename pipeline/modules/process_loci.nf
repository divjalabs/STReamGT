process PROCESS_LOCI{


    publishDir params.intermediate_dir, mode: 'copy'

    input:
    tuple val(locus), val(type), val(sequence), path(assigned_reads_file)

    
    output:
    tuple val(locus), val(type), val(sequence), path("${locus}.csv"), path("${locus}_counts.csv")

    script:
    """
    obigrep -a experiment=${locus} --skip-empty assigned_reads.fastq > ${locus}.fastq
    obiuniq --skip-empty -m sample ${locus}.fastq > ${locus}_uniq.fastq
    obimatrix ${locus}_uniq.fastq > ${locus}_counts.csv
    obicsv -i -s ${locus}_uniq.fastq > ${locus}.csv
    """
}
