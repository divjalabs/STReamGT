---

editor_options: 
  markdown: 
    wrap: 72
---

# STReamGT — User Guide

Welcome! This guide walks you through using the STReamGT web app from start to finish: creating an account, submitting your sequencing data for analysis, and downloading your results. No bioinformatics experience is needed.

------------------------------------------------------------------------

## 1. What STReamGT does

STReamGT takes the raw sequencing data (FASTQ files) from your kit and turns it into **genotypes** — the genetic profile of each sample — together with a **quality-control (QC) report** so you can see how well the run performed. You upload your data, the platform runs the analysis for you, and you download the results when it's done. A typical run takes a couple of hours depending on data size. You will be notified via email when the analysis is done.

**What you get back:** a table of genotypes per sample, supporting summary tables, and interactive HTML reports you can open in your browser. See [Section 6 — Getting your results](#6-getting-your-results).

------------------------------------------------------------------------

## 2. Getting started

### Create an account

1.  Open the app and click **Register** (or go to the *Create account* page).
2.  Enter your **email**, a **password** (at least 8 characters), and your **organisation** (optional).
3.  Click **Register**. You're logged in immediately and taken to your dashboard.

### Log in later

Use **Log in** with the same email and password. Use **Log out** (top-right) when you're done.

> Your account starts empty. Kits are assigned to you by an administrator — see the next section.

------------------------------------------------------------------------

## 3. Your kits

Open **My kits** from the top menu. This lists every kit an administrator has assigned to your account. Each kit is a pre-configured library — it already knows which genetic markers and tag layout to use, so you don't have to configure anything.

**Kit status** tells you where a kit is in its lifecycle:

| Status | What it means | What you can do |
|------------------------|------------------------|------------------------|
| **sent** | The physical kit has been shipped to you. | Click **Mark received** when it arrives. |
| **received** | You've confirmed the kit arrived. | Run an analysis with it (see Section 4). |
| **analysed** | An analysis for this kit has already finished successfully. | Locked — each kit is analysed once. Contact an admin to re-enable it. |
| **reanalyse** | An admin has re-opened the kit. | You can submit it again. |

> **Don't see a kit you expect?** Kits are assigned by an administrator. If one is missing, contact your admin.

------------------------------------------------------------------------

## 4. Starting an analysis

Click **New analysis** in the top menu. The form has three parts: choose a kit, provide your FASTQ data, and describe your sample batches.

### Step 1 — Choose your kit (library)

Pick your kit from the **Library (kit) name** dropdown. The page then shows the kit's species and its available **tag columns** (labelled PP1, PP2, …). These come pre-set from the kit.

> If the kit shows status **analysed**, submission is blocked. Ask an admin to re-enable it.

### Step 2 — Provide your FASTQ data

Each analysis uses **one pair of FASTQ files** — a forward read file (**R1**) and a reverse read file (**R2**) — shared across all of your sample batches. You have two options:

- **Upload** — choose your R1 and R2 files (`.fastq` or `.fastq.gz`). A progress bar shows the upload; **large files (often \~2 GB) can take a while, so keep the tab open.**
- **Server path / link** — instead of uploading, paste a location the platform can read: an `https://` download link, or a path/key already stored on the server.

Then set the **Expected read number** — roughly how many reads you expect the run to produce (default 10,000,000). This is used for a safety check and for your QC report — see [Step 5 low-read check](#5-tracking-progress).

### Step 3 — Describe your sample batches

A **batch** is a group of samples that share a plate layout. Most runs have a single batch, but you can add more. For each batch:

1.  **Batch name** — a label of your choice (e.g. `HRM01`).
2.  **Samples** — provide the sample names in plate order, one of two ways:
    - **Upload Excel** — an `.xlsx` sample sheet, or
    - **Enter samples** — type names directly into the on-screen 96-well plate. **All 96 wells must be filled** before you can submit.
3.  **Tags (PP columns)** — tick the tag columns used for this batch. All are ticked by default; untick any you didn't use.

Use **+ add another sample batch** to add more, or **remove** to delete one.

### Step 4 — Submit

Click **Submit analysis**. You're taken straight to the job page, where you can watch it run.

------------------------------------------------------------------------

## 5. Tracking progress

The job page updates itself automatically — no need to refresh. Your analysis moves through these steps:

**queued → staging → running → uploading → succeeded**

- **queued** — waiting to start.
- **staging** — the platform is preparing your inputs.
- **running** — the genotyping analysis is underway.
- **uploading** — results are being saved.
- **succeeded** — done! Results appear on the page.

You'll also see your sample batches listed with their species and selected tags.

### The low-read check (confirmation needed)

If your uploaded FASTQ has **fewer reads than you expected** (from Step 2), the job pauses in a state called **awaiting_confirmation** instead of running. The page shows the actual read count versus your expected number and asks you to decide:

- **Run anyway** — proceed despite the lower read count (results may be lower quality).
- **Cancel** — stop the job (e.g. if you realize you uploaded the wrong file).

This protects you from spending a run on data that may be incomplete.

### Email notifications

You'll receive an email when your job: - **finishes successfully** (with a link to the results), - **is paused** for the low-read check above, or - **fails**.

You can always return to **My jobs** to see all your analyses and their statuses.

------------------------------------------------------------------------

## 6. Getting your results

When a job reaches **succeeded**, a **Results** list appears on the job page. Each result has a **Download** link; the interactive reports also have an **Open ↗** link to view them in your browser without downloading.

| Result | What it is |
|------------------------------------|------------------------------------|
| **genotypes** | The main output — the genetic profile (alleles) called for each sample. |
| **positions** | Marker/position details underlying the genotypes. |
| **frequency** | Allele frequency summaries. |
| **consensus** | Consensus sequences derived from the run. |
| **reads_summary** | Read counts and QC numbers per sample. |
| **html_report** | An interactive QC report — open it in your browser (**Open ↗**). |
| **consensus_report** | An interactive consensus report — open it in your browser (**Open ↗**). |
| **ngsfilter** | The technical filter/config file used for the run (for reference). |

Start with **genotypes** for your results and the **html_report** to check quality.

------------------------------------------------------------------------

## 7. Troubleshooting & FAQ

**My job failed.** The job page shows an error message, and you'll get an email. Common causes are corrupted or mismatched FASTQ files, or sample sheets that don't match the data. Check your inputs and try a new analysis; if it persists, send the error text to your admin.

**"This kit has already been analysed."** Each kit can be analysed only once. To run it again, ask an administrator to switch it to **reanalyse**.

**I can't find my kit.** Kits are registered and assigned by an administrator. If one is missing from **My kits**, contact your admin.

**My upload is slow or seems stuck.** FASTQ files are large. Keep the browser tab open until the progress bar completes. On a shaky connection, the **Server path / link** option (Step 2) lets you point at data already stored online instead of uploading.

**"All 96 wells must be filled."** When entering samples on-screen, every well of the plate must have a name before you can submit. If you have fewer samples, use the **Upload Excel** option with your own sample sheet instead.

**Do I have to configure primers or markers?** No. Everything is pre-set in your kit by the team. You only provide FASTQ data and sample names.

------------------------------------------------------------------------

*Need help? Contact your administrator.*
