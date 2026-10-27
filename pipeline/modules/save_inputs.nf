process SAVE_INPUTS {

    input:
    path params.input // correct!

    output:
    path(params.input), emit: saved_inputs

    script:
    """
    mkdir -p ${params.inputs_dir}
    cp ${params.input} ${params.inputs_dir}/
    """
}