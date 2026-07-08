from app.services.samplesheet import serialize_tags, build_input_tsv, BatchRow


def test_serialize_tags_ranges_and_gaps():
    assert serialize_tags(["PP1", "PP2", "PP3", "PP4"]) == "PP1-PP4"
    assert serialize_tags(["PP5", "PP6", "PP7", "PP8"]) == "PP5-PP8"
    assert serialize_tags(["PP3"]) == "PP3"
    # unordered input, with a gap -> grouped runs
    assert serialize_tags(["PP5", "PP1", "PP2"]) == "PP1-PP2,PP5"
    # dedup
    assert serialize_tags(["PP1", "PP1", "PP2"]) == "PP1-PP2"


def test_build_reproduces_reference_input_tsv():
    """Two batches sharing FASTQ/primers/tags CSV, differing by sample sheet + tags,
    reproducing the shape of the committed pipeline/tests/input.example.tsv."""
    tsv = build_input_tsv(
        kit_id="DIVJA240",
        tags_path="/stage/wolf_tags1.csv",
        primers_path="/stage/UA_primers.csv",
        fastq1_path="/stage/reads_1.fastq.gz",
        fastq2_path="/stage/reads_2.fastq.gz",
        batches=[
            BatchRow(sample_path="/stage/HRM01.xlsx", selected_tags=["PP1", "PP2", "PP3", "PP4"]),
            BatchRow(sample_path="/stage/HRM02.xlsx", selected_tags=["PP5", "PP6", "PP7", "PP8"]),
        ],
    )
    lines = tsv.strip().split("\n")
    assert lines[0].split("\t") == [
        "kit_id", "sample_path", "tags", "tags_path", "primers_path", "fastq1_path", "fastq2_path"
    ]
    assert len(lines) == 3  # header + 2 batches
    r1 = lines[1].split("\t")
    assert r1[0] == "DIVJA240" and r1[2] == "PP1-PP4" and r1[1].endswith("HRM01.xlsx")
    assert lines[2].split("\t")[2] == "PP5-PP8"
    # FASTQ + primers + tags CSV identical across rows (matches the .take(1) assumption)
    assert lines[1].split("\t")[3:] == lines[2].split("\t")[3:]
