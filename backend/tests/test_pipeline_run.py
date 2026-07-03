import os

import pytest

from app.models.enums import ResultKind
from app.worker import pipeline_run as pr


def test_build_nextflow_cmd_has_no_outdir_override():
    cmd = pr.build_nextflow_cmd(
        pipeline_dir="/app/pipeline", input_tsv="/s/input.tsv", run_dir="/s",
        profile="docker", min_identity=0.9, min_overlap=20,
    )
    assert "run" in cmd and cmd[cmd.index("run") + 1].endswith("main.nf")
    assert "--outdir" not in cmd            # rely on pipeline default (kit_id nesting)
    assert "docker" in cmd and "--min_identity" in cmd


def test_build_render_cmd_passes_params():
    cmd = pr.build_render_cmd(
        rmd_path="/p/Genotype_stat.Rmd", output_html="/s/report.html",
        expected_reads=10_000_000, run_stats="/s/sum.csv",
        alleles="/s/gen.txt", positions="/s/pos.txt",
    )
    assert cmd[0] == "Rscript"
    expr = cmd[2]
    assert "rmarkdown::render" in expr and "expected_read_number=10000000" in expr
    assert "alleles='/s/gen.txt'" in expr


def test_collect_results_maps_kinds(tmp_path):
    kit = "DIVJA240"
    res = tmp_path / kit / "results"
    rep = tmp_path / kit / "reports"
    res.mkdir(parents=True)
    rep.mkdir(parents=True)
    (res / f"{kit}_genotypes.txt").write_text("x")
    (res / f"{kit}_positions.txt").write_text("x")
    (res / f"{kit}_frequency_of_sequences_by_marker.txt").write_text("x")
    (rep / f"{kit}_reads_summary.csv").write_text("x")

    found = pr.collect_results(str(tmp_path), kit)
    kinds = {r.kind for r in found}
    assert kinds == {
        ResultKind.genotypes, ResultKind.positions,
        ResultKind.frequency, ResultKind.reads_summary,
    }
    assert pr.find_result(found, ResultKind.genotypes).endswith("_genotypes.txt")


def test_collect_results_empty_when_missing(tmp_path):
    assert pr.collect_results(str(tmp_path), "NOPE") == []


def test_samples_text_to_rows_variants():
    rows = pr.samples_text_to_rows("TPositionId,SPositionBC\nA1,SAMP1\nB2,SAMP2\n")
    assert rows == [{"TPositionId": "A1", "SPositionBC": "SAMP1"},
                    {"TPositionId": "B2", "SPositionBC": "SAMP2"}]
    # tab and whitespace separated, header skipped
    assert pr.samples_text_to_rows("A1\tS1\nC3 S3")[0]["SPositionBC"] == "S1"


def test_samples_text_bad_line_raises():
    with pytest.raises(ValueError):
        pr.samples_text_to_rows("A1\nB2\n")  # only one field per line


def test_write_sample_xlsx_roundtrip(tmp_path):
    from openpyxl import load_workbook

    dest = tmp_path / "plate.xlsx"
    pr.write_sample_xlsx([{"TPositionId": "A1", "SPositionBC": "S1"}], str(dest))
    wb = load_workbook(dest)
    ws = wb.active
    assert [c.value for c in ws[1]] == ["TPositionId", "SPositionBC"]
    assert [c.value for c in ws[2]] == ["A1", "S1"]
