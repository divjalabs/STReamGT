"""Parse a kit's primers CSV and tags CSV into structured catalog data.

The reference files (STReam_primers_tags/) have inconsistent shapes across species:
  - headers: locus,primerF,primerR,type[,motif][,sequence]
  - `type` may be upper/lower case (microsat / SNP)
  - some files carry a UTF-8 BOM and/or trailing empty columns
So the parsing here is deliberately lenient.
"""
from __future__ import annotations

import csv
import io

_TYPE_ALIASES = {
    "microsat": "microsat",
    "microsatellite": "microsat",
    "str": "microsat",
    "snp": "snp",
}


def _norm_key(k: str) -> str:
    return k.replace("﻿", "").strip().lower()


def parse_primers_csv(text: str) -> list[dict]:
    """Return one dict per locus with keys: locus, type, primer_f, primer_r, motif, sequence.

    Rows without a locus are skipped. Unknown/blank type -> raised so bad files fail loudly.
    """
    text = text.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("empty primers CSV")
    keymap = {_norm_key(f): f for f in reader.fieldnames if f is not None}

    def get(row: dict, *names: str) -> str | None:
        for n in names:
            src = keymap.get(n)
            if src is not None:
                v = (row.get(src) or "").strip()
                if v:
                    return v
        return None

    out: list[dict] = []
    for row in reader:
        locus = get(row, "locus")
        if not locus:
            continue
        raw_type = (get(row, "type") or "").lower()
        ptype = _TYPE_ALIASES.get(raw_type)
        if ptype is None:
            raise ValueError(f"locus {locus!r} has unrecognized type {raw_type!r}")
        out.append(
            {
                "locus": locus,
                "type": ptype,
                "primer_f": get(row, "primerf", "primer_f"),
                "primer_r": get(row, "primerr", "primer_r"),
                "motif": get(row, "motif"),
                "sequence": get(row, "sequence"),
            }
        )
    if not out:
        raise ValueError("no valid primer rows found")
    return out


def parse_tag_columns(text: str) -> list[dict]:
    """From a wide tags CSV header (Position,PP1,PP2,...), return the PP columns.

    Returns [{"name": "PP1", "ordinal": 1}, ...] ordered by their numeric suffix.
    """
    text = text.lstrip("﻿")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("empty tags CSV")
    cols = []
    for h in header:
        h = h.strip()
        if not h or h.lower() == "position":
            continue
        cols.append(h)
    if not cols:
        raise ValueError("no PP tag columns found in tags CSV header")

    def num(name: str) -> int:
        digits = "".join(ch for ch in name if ch.isdigit())
        return int(digits) if digits else 0

    return [{"name": c, "ordinal": num(c)} for c in sorted(cols, key=num)]
