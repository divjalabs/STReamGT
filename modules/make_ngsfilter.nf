process MAKE_NGSFILTER {

    container 'python_scripts_only'

    input:
    tuple path(sample_path), val(tags), path(tags_path), path(primers_path)

    output:
    path("${params.kit_id}_ngsfilter_${tags}.csv")

    script:
    """

    make_ngsfilter.py --kit_id ${params.kit_id} --sample_path ${sample_path} --tags ${tags} --tags_path ${tags_path} --primers_path ${primers_path}
    """
}

process MERGE_NGSFILTER {

    container 'obitools4_py'  
    
    publishDir params.intermediate_dir, mode: 'copy'

    input:
    path ngsfilter_files

    output:
    path "${params.kit_id}_ngsfilter.csv"

    script:
    """
    # remove duplicate headers when merging
    awk 'FNR==1 && NR!=1 {next} {print}' ${ngsfilter_files.join(' ')} > ${params.kit_id}_ngsfilter.csv
    """
}
