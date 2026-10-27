# Consensus logic: MisBase Access DB vs. `callConsensus.py`

This documents how the legacy MisBase Access database builds consensus genotypes
versus the Nextflow pipeline (`pipeline/bin/callConsensus.py`), and records which
metrics were reconciled to match the database.

## Source of truth in the database

- **Module:** `mConsensusGenotypes`, procedure `CreateConsensusTableNGS` (the NGS
  variant of `CreateConsensusTable`).
- **Driver:** macro `mcrCreateConsensus`, form `frmRunConsensusGenotypes`.
- **Input:** `tblSeqLinkNGS_Genotypes` (called alleles, one row per
  Sample × Run × TagCombo × Marker × allele, with `Read_Count`, `flag`, `called`).
- **Output:** `atblConsensusGenotypes` (one row per Sample × Marker).
- **Thresholds:** `stblSettings` (`AlleleRepeatsAccept`, `AlleleRepeatsAcceptHomo`,
  `AlleleRepeatsAcceptRelSType`, `AlleleRepeatsAcceptRelHomo`, `FlagAccept`).
- **Allele names:** `atblNGSImportAlleles` (`AlleleName = Length[_Variant]`).

The database's fundamental unit is the **amplification** (one PCR reaction — in the
DB, one Sample × Run × TagCombo; in the pipeline, one well = `Plate` + `Position`).
All success/quality/dropout metrics are ratios over amplifications, **not** over
allele-observation counts.

## Same in both

- Consume only `called = True` rows; read a per-row `flag`.
- Accept an allele into the consensus when it is seen more than an acceptance
  threshold, with **separate homozygote vs. heterozygote thresholds**.
- Track confirmed-but-flagged alleles and unconfirmed alleles separately.
- Name alleles `Length[_Variant]`.

## Differences

| Aspect | Access DB (`CreateConsensusTableNGS`) | Pipeline (original `callConsensus.py`) |
|---|---|---|
| Replicate unit | Amplification = Sample × Run × TagCombo | Allele-observation counts; `NAmp` = distinct plates |
| **QualityIndex** | `perfect_amps / N_Amps`, where a *perfect* amp reproduces the full consensus genotype (`Allele_1`,`Allele_2`) | `NAmpOK / NAmp`, a count-based proxy (not a per-amp genotype match) |
| **ADO** | Het consensus only: `N_SuccessAmps − N_HetAmps` (successful amps that showed a single allele = dropout events); `0` for homozygotes | `abs(count(Al1) − count(Al2))` for a het; `0` for a hom |
| **ADO_Rate** | `ADO / N_SuccessAmps` | `ADO / NAmpOK` |
| **SuccessRate** | Distinct field: `100 × N_SuccessAmps / N_Amps` (amps that yielded ≥1 usable allele) | Not produced; `Success` was `QualityIndex × 100` |
| Thresholds | 4 values (homo/het × regular/reference sample type) | 2 values (homo/het), no sample-type dimension |
| Flag confirmation | Flagged allele confirmed if ≥ `FlagAccept` clean copies exist at the sample×marker | Confirmed if ≥ 1 clean replicate exists |
| 3+ alleles in an amp | Written as an Error; alleles blanked | Extra alleles spilled into `Al3`/`Al4`/unconfirmed |
| Extra DB metrics | `N_Al1/2`, `NF_Al1/2`, `ReadsPerAmp`, `SD_ReadsPerAmp`, `N_DifferentAlleles`, `FalseAlleles`, `MultipleAlleles`, `TotalADO_Rate`, `Reliability` | Not produced |
| Variant numbering | By discovery order, persisted DB-wide | By frequency rank within the current library (unless a reference table is supplied) |
| State | Incremental; `Locked` genotypes preserved, only `Consensus2Do` samples recomputed | Stateless per-kit batch |

## What was reconciled

`QualityIndex`, `ADO`/`ADORate`, and `SuccessRate` were reimplemented to match the
database. They are now **amplification-based**, using the `Plate`/`Position` columns
in the merged genotypes to group called alleles into amplifications and the
`positions` table for the total amplification count `N_Amps` (which includes failed
amplifications that produced no called allele):

- **N_Amps** — number of amplifications attempted for the Sample × Marker
  (distinct `Plate` × `Position` in `positions`; the `NAmp` output column).
- **N_SuccessAmps** (`NAmpOK`) — amplifications that yielded ≥ 1 usable allele
  (an allele is *usable* in an amp if it is clean, or flagged but the same allele
  is seen clean elsewhere at the Sample × Marker).
- **SuccessRate** (the `Success` column) — `100 × N_SuccessAmps / N_Amps`.
- **QualityIndex** — `perfect_amps / N_Amps`, where a perfect amp's set of usable
  alleles equals the consensus genotype `{Allele1, Allele2}`.
- **ADO** — for a heterozygous consensus, `N_SuccessAmps − N_HetAmps`
  (single-allele successful amps); `0` for homozygotes. **ADORate** = `ADO / N_SuccessAmps`.
- **FalseAlleles** (exact DB formula) — sum of the observation counts of the 3rd–5th
  most frequent alleles at the Sample × Marker (everything past the top-2 genotype).
- **ReadsPerAmp / SD_ReadsPerAmp** (inferred) — mean and sample SD of total `Read_Count`
  per successful amplification (summed over that amp's usable-allele rows). The DB's exact
  formula was not recoverable from the compressed VBA; this follows the column names/types
  (`ReadsPerAmp` Long Integer, `SD_ReadsPerAmp` Double). SD is `0` when there is < 2 amps.

> Edge case (faithful to the DB): a well showing only a *false* allele still counts as a
> successful, non-heterozygous amp, so it feeds `N_SuccessAmps` and therefore inflates ADO
> (`N_SuccessAmps − N_HetAmps`). The DB's literal formula behaves the same way. Rare in practice.

## Actual DB parameters (Run Consensus dialog)

Values in production (`stblSettings`), with their pipeline mapping:

| Run Consensus dialog | `stblSettings` | Value | Pipeline |
|---|---|---|---|
| Repeats to accept allele (heterozygote) | `AlleleRepeatsAccept` | 2 | `AlleleAcceptanceThreshold_hetero` = 2 |
| Repeats to accept, homozygotes | `AlleleRepeatsAcceptHomo` | 2 | `AlleleAcceptanceThreshold` = 2 |
| Repeats to accept, reliable sample types | `AlleleRepeatsAcceptRelSType` | 2 | — (no sample-type dimension) |
| Repeats to accept, reliable homozygotes | `AlleleRepeatsAcceptRelHomo` | 2 | — |
| Min clean observations to accept a flagged allele | `FlagAccept` | 1 | "usable" rule: ≥1 clean copy |
| Min replicates before discard | `MinNumOfReplicates` | 2 | sample-QC (downstream) |
| Min amplification success rate | `MinAverageSuccessRate` | 10.0% | sample-QC (downstream) |
| Min Quality Index (Miquel 2006) | `MinQualityIndex` | 0.1 | sample-QC (downstream) |
| Min repeats above which discard if unreliable | `MinNumRepsReliability` | 12 | sample-QC (downstream) |
| Reliotype reliability threshold | `GenotypeReliabilityThreshold` | — | not in pipeline |
| Run LIMITED consensus (only new/selected) | `ConsensusRunOnlyNew` | yes | N/A (stateless batch) |

**Acceptance operator:** the dialog reads "repeats *required* to accept", so the DB accepts
an allele at `count >= threshold`. `callConsensus.py` therefore uses `len(rows) >= threshold`
(not `>`), with `parameters.json` holding the DB values directly (2 / 2). All four DB threshold
variants are 2 in production, so the missing reference-sample-type dimension has no effect here.

`FlagAccept = 1` matches the pipeline's rule (a flagged allele is confirmed by ≥1 clean copy).
The `MinNumOfReplicates` / `MinAverageSuccessRate` / `MinQualityIndex` / `MinNumRepsReliability`
values are sample-level **discard** gates applied after consensus, not inputs to the per-genotype
metrics computed here.

### Deliberate simplifications vs. the DB

- Perfect-amp matching compares the amplification's usable-allele **set** to the
  consensus genotype set (order-independent), rather than positional
  `Allele_1`/`Allele_2` equality. Equivalent in practice because both are sorted
  consistently.
- Flag confirmation uses ≥ 1 clean copy (matches production `FlagAccept = 1`), not a
  configurable `FlagAccept`.
- Not yet implemented: sample-type-dependent thresholds; `N_DifferentAlleles`,
  `MultipleAlleles`, `TotalADO_Rate`, `Reliability`; the "3+ alleles ⇒ Error" per-amp
  rejection; and the sample-level discard gates (`MinQualityIndex`, `MinAverageSuccessRate`,
  `MinNumOfReplicates`, `MinNumRepsReliability`).
