# STReamGT — Glossary

Plain definitions of the terms you'll meet in the app and in your results. 
------------------------------------------------------------------------

## The lab side

### Kit

A physical library you receive in the post: a 96-well (8×12) plate preloaded for one species, together with the **tags** and **primers** needed to sequence it. You fill the wells with your samples, run them, and upload the reads. In the app a kit already knows its species, **primer panel** and **tag** layout, so there's nothing to configure. A kit moves through statuses — **sent → received → analysed** (and **reanalyse** if you run it again). One kit = one library = up to 96 wells.


### Primer panel

The set of PCR primers a kit uses — one pair per **marker**. Panels are species-specific (e.g. `UA` for brown bear, `LL_MPA` for lynx) and decide which markers you get genotypes for. Sex and SNP markers also carry a reference sequence in the panel, so the caller knows what an X versus a Y, or each SNP allele, should look like.

### Tags (PP columns)

Short DNA barcodes attached to your fragments so a pooled sequencing run can be un-pooled afterwards. Each **PP column** is one physical primer plate carrying one set of tags. Because every well-and-plate combination gets a unique tag pair, the pipeline can take a pile of mixed reads and sort each one back to the exact well it came from. You choose which PP columns a batch uses when you submit.

### Replicates

The same sample amplified more than once — usually across several PP columns/wells. Noninvasive samples (scat, hair) give low-DNA, error-prone reads, so a single PCR can't be trusted. Replicates let the caller keep the alleles that show up repeatedly and drop the one-off artifacts. See **Consensus**.

### Controls

Wells with a known expected result, there to catch trouble:

-   **Negative controls** — a **blank** (no DNA) and a **PCRneg** (PCR with no template). They should come back empty; reads here mean contamination.
-   **Positive control** — a known reference animal that should reproduce a known genotype. If it doesn't, something in the run drifted.

Controls are typed (blank/sequencing, PCR, extraction, positive), coloured on the plate, and checked in the QC report. They are never treated as real animals.

------------------------------------------------------------------------

## The analysis

### Analysis 

The bioinformatics pipeline run that turns your raw reads into genotypes. It pairs and filters the reads, demultiplex them by tags and primers, calls alleles in every replicate, and builds a **consensus** per sample. You start it from the app — one submission is one **run** (a *job*) — and a couple of hours later you get result files and reports. No bioinformatics knowledge needed.

### Reads / FASTQ

The sequencer's raw output: millions of short DNA sequences in `.fastq` files. This is what you upload; everything else is derived from it.

### Marker (locus)

One place in the genome that gets genotyped — a microsatellite (STR) or a SNP. The panel lists them, and genotypes are reported per marker. 

### Allele

One variant of a marker. Its identity is a DNA sequence, but it also has a name. Allele names are assigned per project and can differ from the per-kit names in your raw result files, so always match on the sequence, not the name.

Microsatellite alleles mostly differ by length (number of motif repeats), so they are named by fragment length, with a suffix (e.g. 142_2) when two sequences of the same length differ. The suffix is assigned based on frequency: less frequent alleles receive higher suffix numbers. When a project's first kit is assigned, allele names are generated. If a new variant of an allele with the same length is added later, it receives the next available suffix number. SNP allele names follow the same rules.


### Genotype

A sample's two alleles at a marker — two if heterozygous, one repeated if homozygous. Stitched across all markers, the multi-locus genotype is effectively a DNA fingerprint that identifies an individual. The **consensus genotype** is the version agreed across replicates.

### Consensus

The genotype the app keeps after weighing the replicates: an allele is accepted only when it appears in enough replicate wells (the homozygote / heterozygote thresholds). This is what separates a true allele from stutter or dropout, and it's what **matching** compares.

------------------------------------------------------------------------

## Organising your data

### Project

 The main workspace after the bioinfo analysis. A project contains the **allele-name catalog**, holds **populations** and **studies**, and is where you have a control on **consensus genotypes** and run animal **matching**. One project is restricted to one animal species - you need to create separate projects for different model objects. You can share a project with colleagues, export or import it.

### Population

A group of animals treated as one gene pool — for example the Dinaric wolf population. Matching only compares samples **within the same population**, and allele frequencies and animal groupings are worked out per population. A sample with no population won't be matched.

### Study

A sampling effort inside a project — say "2025 winter monitoring" or a single field season. It groups samples and can be switched in or out of matching. Attaching a kit to a study drops that kit's samples into the study (and its population).

### Sample

One biological specimen — scat, hair, blood or tissue — that you genotyped. It came from a kit well via a run, lives in a project (usually a population and study too), and carries a consensus genotype, a QC verdict and a genetic sex. Controls are samples as well, just flagged and never matched.

### Matching

Comparing samples' genotypes within a population to decide which came from the same animal, allowing for a little genotyping error. The result is the animal groupings above.

### Animal (individual)

A single real animal, reconstructed after the fact by **matching**: samples whose genotypes agree closely enough are grouped as the same individual. One animal usually has several samples — the same wolf sampled at different times and places. This is the point of the whole workflow: turning a pile of scats into a count of individuals.

------------------------------------------------------------------------