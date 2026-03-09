process PROCESS_LOCI{

    container 'obitools4'


    script:
    """
    mkdir -p ${kit_id}
    obigrep -a experiment=${loci} assigned_reads.fastq >${loci}.fastq
    obiuniq -m sample ${loci}.fastq > ${loci}_uniq.fastq
    obiannotate -k count -k merged_sample -k obimultiplex_forward_tag -k obimultiplex_reverse_tag ${loci}_uniq.fastq > ${loci}_cleaned.fastq
    obicsv --auto -s ${loci}_cleaned.fastq > ${loci}.csv
    """