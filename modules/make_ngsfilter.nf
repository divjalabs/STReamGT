process MAKE_NGSFILTER {

    container 'obitools4_py'

    input:
    tuple val(kit_id), path(sample_path), val(tags), path(tags_path), path(primers_path)

    output:
    path("${kit_id}_ngsfilter_${tags}.csv")

    script:
    """

    make_ngsfilter.py --kit_id ${kit_id} --sample_path ${sample_path} --tags ${tags} --tags_path ${tags_path} --primers_path ${primers_path}
    """
}

process MERGE_NGSFILTER {

    container 'obitools4_py'  
    
    publishDir "intermediate", mode: 'copy'

    input:
    val kit_id
    path ngsfilter_files

    output:
    path "${kit_id}/${kit_id}_ngsfilter.csv"

    script:
    """
    mkdir -p ${kit_id}

    # remove duplicate headers when merging
    
    awk 'FNR==1 && NR!=1 {next} {print}' ${ngsfilter_files.join(' ')} > ${kit_id}/${kit_id}_ngsfilter.csv
    """
}
