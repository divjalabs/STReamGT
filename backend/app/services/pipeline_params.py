"""Pipeline tuning parameters: defaults from pipeline/bin/parameters.json + a per-run merge.

The pipeline scripts (callAlleleUL/callConsensus/make_report) read these thresholds; a job may
override any of them, and the worker writes the merged set to a per-run parameters.json.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path


def _find_parameters_file() -> Path:
    env = os.environ.get("PIPELINE_DIR")            # /app/pipeline in the image
    if env:
        p = Path(env) / "bin" / "parameters.json"
        if p.is_file():
            return p
    for base in Path(__file__).resolve().parents:   # local/tests: walk up to the repo
        p = base / "pipeline" / "bin" / "parameters.json"
        if p.is_file():
            return p
    raise FileNotFoundError("pipeline parameters.json not found (set PIPELINE_DIR)")


@lru_cache(maxsize=1)
def default_parameters() -> dict:
    return json.loads(_find_parameters_file().read_text())


def _coerce(default, val):
    if isinstance(default, bool):                   # bool before int (bool is an int subclass)
        return val if isinstance(val, bool) else str(val).strip().lower() in ("1", "true", "yes", "y", "t")
    if isinstance(default, int):
        return int(float(val))
    if isinstance(default, float):
        return float(val)
    return str(val)


def merge_parameters(overrides: dict | None) -> dict:
    """Defaults overlaid with known overrides, each coerced to the default value's type.
    Unknown keys are ignored; a value that won't coerce keeps the default."""
    merged = dict(default_parameters())
    for key, val in (overrides or {}).items():
        if key not in merged or val is None:
            continue
        try:
            merged[key] = _coerce(merged[key], val)
        except (TypeError, ValueError):
            continue
    return merged
