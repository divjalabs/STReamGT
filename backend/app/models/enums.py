"""Enumerations used across the data model."""
from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"


class JobStatus(str, enum.Enum):
    queued = "queued"
    staging = "staging"       # downloading inputs from S3, building input.tsv
    running = "running"       # nextflow run in progress
    rendering = "rendering"   # rendering the R report
    uploading = "uploading"   # pushing results to S3
    succeeded = "succeeded"
    failed = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.succeeded, JobStatus.failed)


class PrimerType(str, enum.Enum):
    microsat = "microsat"
    snp = "snp"


class ControlKind(str, enum.Enum):
    negative = "negative"
    positive = "positive"


class FastqSource(str, enum.Enum):
    upload = "upload"     # multipart uploaded to S3
    server = "server"     # references an existing path/key on the server/bucket
    link = "link"         # external URL to fetch


class ResultKind(str, enum.Enum):
    genotypes = "genotypes"
    positions = "positions"
    frequency = "frequency"
    consensus = "consensus"
    reads_summary = "reads_summary"
    html_report = "html_report"
    ngsfilter = "ngsfilter"


class KitStatus(str, enum.Enum):
    sent = "sent"          # admin registered + sent the physical kit to the client
    received = "received"  # client confirmed receipt / registered it
    analysed = "analysed"  # a genotyping job for this kit has succeeded (set automatically)
    reanalyse = "reanalyse"  # admin re-approved an analysed kit so it can be submitted again
