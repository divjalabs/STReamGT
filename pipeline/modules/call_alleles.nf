process CALL_ALLELES{
    
    input:
    tuple val(locus_name), val(locus_type), val(locus_sequence), path(locus_csv), path(counts_csv)
    path ngsfilter_file

    output:
    tuple(
    path("${params.kit_id}_${locus_name}_genotypes.txt"),
    path("${params.kit_id}_${locus_name}_frequency_of_sequences_by_marker.txt"),
    path("${params.kit_id}_${locus_name}_positions.txt"))

    script:
    """
    callAlleleUL.py --kit_id ${params.kit_id} --sample_count ${counts_csv} --sequence_data ${locus_csv} --locus_name ${locus_name} --locus_type ${locus_type} --locus_sequence ${locus_sequence} --ngsfilter_path ${ngsfilter_file}
    """
    
}

process MERGE_ALLELES{

    publishDir params.results_dir, mode: 'copy'

    input:
    path genotypes_files
    path freq_files
    path pos_files


    output:
    path("${params.kit_id}_genotypes.txt")
    path("${params.kit_id}_frequency_of_sequences_by_marker.txt")
    path("${params.kit_id}_positions.txt")

    script:
    """
    mkdir -p results
    
    # ---- merge genotypes ----
    awk 'FNR==1 && NR!=1 {next} {print}' ${genotypes_files.join(' ')} > ${params.kit_id}_genotypes.txt

    # ---- merge frequency ----
    awk 'FNR==1 && NR!=1 {next} {print}' ${freq_files.join(' ')} > ${params.kit_id}_frequency_of_sequences_by_marker.txt

    # ---- merge positions ----
    awk 'FNR==1 && NR!=1 {next} {print}' ${pos_files.join(' ')} > ${params.kit_id}_positions.txt
    """
}