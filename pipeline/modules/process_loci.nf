process PROCESS_LOCI{

    // Cap concurrency so parallel per-locus obiuniq dereplications don't OOM the head task:
    // on 8 vCPU this runs at most 2 loci at once, each obiuniq bounded to task.cpus threads.
    cpus 4

    publishDir params.intermediate_dir, mode: 'copy'

    input:
    tuple val(locus), val(type), val(sequence), path(assigned_reads_file)

    
    output:
    tuple val(locus), val(type), val(sequence), path("${locus}.csv"), path("${locus}_counts.csv")

    script:
    """
    obigrep -a experiment=${locus} --skip-empty ${assigned_reads_file} > ${locus}.fasta
    obiuniq --skip-empty --max-cpu ${task.cpus} -m sample ${locus}.fasta > ${locus}_uniq.fasta
    obimatrix ${locus}_uniq.fasta > ${locus}_counts.csv
    obicsv -i -s ${locus}_uniq.fasta > ${locus}.csv
    """
}
