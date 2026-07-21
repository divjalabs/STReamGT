process PROCESS_LOCI{


    publishDir params.intermediate_dir, mode: 'copy'

    input:
    tuple val(locus), val(type), val(sequence), path(assigned_reads_file)

    
    output:
    tuple val(locus), val(type), val(sequence), path("${locus}.csv"), path("${locus}_counts.csv")

    script:
    """
    obigrep -a experiment=${locus} --skip-empty ${assigned_reads_file} > ${locus}.fasta
    obiuniq --skip-empty -m sample ${locus}.fasta > ${locus}_uniq.fasta
    obimatrix ${locus}_uniq.fasta > ${locus}_counts.csv
    obicsv -i -s ${locus}_uniq.fasta > ${locus}.csv
    """
}
