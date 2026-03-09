process MAKE_NGSFILTER {

    container 'str-py'

    publishDir { "intermediate" }, mode: 'symlink'

    input:
    tuple val(kit_id), path(sample_path), val(tags), path(tags_path), path(primers_path), path(r1), path(r2)

    output:
    path("${kit_id}/${kit_id}_ngsfilter.csv")

    script:
    """
    mkdir -p ${kit_id}

    make_ngsfilter.py --kit_id ${kit_id} --sample_path ${sample_path} --tags ${tags} --tags_path ${tags_path} --primers_path ${primers_path}
    """
}


