process DEMULTIPLEX_READS {
    
    publishDir params.intermediate_dir, mode: 'symlink'

    input:
    path assembled_reads
    path ngsfilter_file

    output:
    path("assigned_reads.fastq"), emit: assigned_reads
    path("ngsfilter_stat.txt"), emit: ngsfilter_stats

    script:
    """
    obimultiplex --skip-empty -s ${ngsfilter_file} ${assembled_reads} -u not_assigned.fastq > assigned_reads.fastq
    obicsv -k obimultiplex_error not_assigned.fastq > obimultiplex_errors.csv
    tail -n+2 obimultiplex_errors.csv | sort  | uniq -c > ngsfilter_stat.txt

    """
}