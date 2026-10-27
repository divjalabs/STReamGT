process DEMULTIPLEX_READS {
    
    publishDir params.intermediate_dir, mode: 'symlink'

    input:
    path assembled_reads
    path ngsfilter_file

    output:
    path("assigned_reads.fasta"), emit: assigned_reads
    path("ngsfilter_stat.txt"), emit: ngsfilter_stats

    script:
    """
    obimultiplex --skip-empty -s ${ngsfilter_file} ${assembled_reads} -u not_assigned.fasta > assigned_reads.fasta
    obicsv -k obimultiplex_error not_assigned.fasta > obimultiplex_errors.csv
    tail -n+2 obimultiplex_errors.csv | sort  | uniq -c > ngsfilter_stat.txt

    """
}