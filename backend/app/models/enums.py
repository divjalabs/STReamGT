"""Enumerations used across the data model."""
from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"


class JobStatus(str, enum.Enum):
    queued = "queued"
    staging = "staging"       # downloading inputs from S3, building input.tsv
    awaiting_confirmation = "awaiting_confirmation"  # FASTQ has < expected reads; paused for the user
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
    positive = "positive"          # positive control — excluded from the noise threshold
    sequencing = "sequencing"      # sequencing / blank negative control
    pcr = "pcr"                    # PCR negative control
    extraction = "extraction"      # extraction negative control
    negative = "negative"          # legacy — pre-typed negative control

    @property
    def is_negative_control(self) -> bool:
        """All non-positive controls feed the progressive noise threshold."""
        return self is not ControlKind.positive

    @property
    def name_token(self) -> str:
        """Short token used in auto-generated control names ({kit}_{token}_{well})."""
        return {
            ControlKind.positive: "pos",
            ControlKind.sequencing: "blank",
            ControlKind.pcr: "pcr",
            ControlKind.extraction: "ext",
            ControlKind.negative: "blank",
        }[self]


class FastqSource(str, enum.Enum):
    upload = "upload"     # multipart uploaded to S3
    server = "server"     # references an existing path/key on the server/bucket
    link = "link"         # external URL to fetch


class ResultKind(str, enum.Enum):
    genotypes = "genotypes"
    positions = "positions"
    frequency = "frequency"
    consensus = "consensus"
    reference_alleles = "reference_alleles"
    reads_summary = "reads_summary"
    html_report = "html_report"
    consensus_report = "consensus_report"
    ngsfilter = "ngsfilter"


class KitStatus(str, enum.Enum):
    sent = "sent"          # admin registered + sent the physical kit to the client
    received = "received"  # client confirmed receipt / registered it
    analysed = "analysed"  # a genotyping job for this kit has succeeded (set automatically)
    reanalyse = "reanalyse"  # admin re-approved an analysed kit so it can be submitted again


# --- animal/sample store + consensus + matching (M1+) ---

class Sex(str, enum.Enum):
    unknown = "unknown"
    male = "male"
    female = "female"


class ProjectRole(str, enum.Enum):
    """Role of a shared (non-owner) user on a project."""
    viewer = "viewer"
    editor = "editor"


class ConsensusSource(str, enum.Enum):
    pipeline = "pipeline"        # ingested from a Nextflow job's consensus output
    recomputed = "recomputed"    # recomputed by the backend consensus service
    manual = "manual"            # hand-edited by a user


class MatchTier(str, enum.Enum):
    none = "none"
    possible = "possible"
    reliable = "reliable"


class MatchCode(str, enum.Enum):
    """Per-marker comparison result between two genotypes (MisBase 4-bit codes)."""
    match = "match"
    pADO1 = "pADO1"   # possible allelic dropout in the reference sample
    pADO2 = "pADO2"   # possible allelic dropout in the search sample
    pADOh = "pADOh"   # homozygote vs homozygote (ambiguous possible dropout)
    ic1 = "ic1"       # one incompatible allele
    ic2 = "ic2"       # both alleles incompatible
    na1 = "na1"       # missing in the reference sample
    na2 = "na2"       # missing in the search sample


class RunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (RunStatus.succeeded, RunStatus.failed)


class MismatchMetric(str, enum.Enum):
    flat = "flat"            # flat allele-mismatch count (Pirog Tm)
    decomposed = "decomposed"  # MisBase ADO/1IC/2IC/total decomposition


class MatchingMode(str, enum.Enum):
    reference_anchored = "reference_anchored"  # primary, incremental-friendly
    clique = "clique"                          # batch maximal-clique QC pass
