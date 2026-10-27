import pytest

from app.services.kit_files import parse_primers_csv, parse_tag_columns

# Header variants seen across STReam_primers_tags/*.csv
UA = "locus,primerF,primerR,type,sequence\nUA_03,gctc,ctgg,microsat,\n"
LL = "locus,primerF,primerR,type,motif\nLL0033,tctc,catc,microsat,AAGA\n"
CE = "locus,primerF,primerR,type,motif,sequence\nCE_003,aaag,tcca,microsat,ATAG,\n"
SEX_SNP = "locus,primerF,primerR,type\nZF1L,GAGC,GGCA,SNP\nZF2L,ACAT,CGTT,SNP\n"
BOM_TRAILING = "﻿locus,primerF,primerR,type,motif,\nCl147,ctgg,tgcc,microsat,GATA,\n"


def test_microsat_uses_motif_snp_uses_sequence():
    rows = parse_primers_csv(LL)
    assert rows[0]["type"] == "microsat" and rows[0]["motif"] == "AAGA"
    assert rows[0]["sequence"] is None  # STR: no sequence

    snp = parse_primers_csv(SEX_SNP)
    assert all(r["type"] == "snp" for r in snp)  # uppercase SNP normalized
    assert snp[0]["motif"] is None and snp[0]["sequence"] is None  # not provided yet


def test_tolerates_bom_and_trailing_columns():
    rows = parse_primers_csv(BOM_TRAILING)
    assert rows[0]["locus"] == "Cl147"
    assert rows[0]["motif"] == "GATA"


def test_header_variants_all_parse():
    for txt in (UA, LL, CE):
        rows = parse_primers_csv(txt)
        assert rows and rows[0]["primer_f"] and rows[0]["primer_r"]


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        parse_primers_csv("locus,primerF,primerR,type\nX,a,b,gibberish\n")


def test_parse_tag_columns():
    header = "Position,PP1,PP2,PP3,PP4,PP5,PP6,PP7,PP8,PP9,PP10,PP11,PP12\n1,A:B,,,,,,,,,,,\n"
    cols = parse_tag_columns(header)
    assert len(cols) == 12
    assert cols[0] == {"name": "PP1", "ordinal": 1}
    assert cols[-1] == {"name": "PP12", "ordinal": 12}  # numeric sort, not lexicographic
