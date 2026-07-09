---

editor_options: 
  markdown: 
    wrap: 72
---

# STReamGT — Admin Guide

*For STReamGT administrators.*

This guide covers the admin-only features of the STReamGT web app: managing primer panels, registering and assigning kits, managing users, and handling client issues. It assumes you're already familiar with the client-facing flow — if not, read the [User Guide](/manuals/user) first, since admins can do everything a client can, plus the extra screens described here.

> **Scope:** this document is about the **web app admin UI** only. For the API-level way to onboard a kit (tokens, `POST /api/kits`, file keys), see [`kit-onboarding.md`](https://github.com/divjalabs/STReamGT/blob/main/docs/kit-onboarding.md). For infrastructure, deployment, and AWS operations, see [`aws-setup.md`](https://github.com/divjalabs/STReamGT/blob/main/docs/aws-setup.md) and [`deployment.md`](https://github.com/divjalabs/STReamGT/blob/main/docs/deployment.md).

------------------------------------------------------------------------

## 1. The admin role

Admins see three extra items in the top menu — **Kits**, **Panels**, and **Users** — alongside the normal *My jobs · My kits · New analysis*.

You become an admin only by being **promoted by another admin** on the **Users** page (see [Section 5](#5-users)).

**Typical admin workflow for onboarding a client:** 1. Make sure a **primer panel** exists for the species → [Section 2](#2-primer-panels). 2. **Register a kit** (or several) and **assign** it to the client's account → [Section 3](#3-kits). 3. The client marks the kit received, submits an analysis, and downloads results. 4. When they need to re-run an already-analysed kit, flip it to **reanalyse** → [Section 4](#4-kit-lifecycle--the-reanalyse-rule).

------------------------------------------------------------------------

## 2. Primer panels

A **panel** is a reusable set of primers for one species/assay. Kits reference a panel, so create the panel first. Open **Panels** from the top menu.

### Add a panel

Fill in the **Add a panel** form: - **Code** — a short identifier, e.g. `UA_primers`, `LL_MPA_primers`. - **Species (common)** — e.g. `brown bear`. - **Species (latin)** — e.g. `Ursus arctos`. - **Description** — optional free text. - **Primers CSV** — upload the panel's `.csv` file.

The canonical reference files live in the repository under `STReam_primers_tags/` (for example `UA_primers.csv` for bear, `LL_MPA_primers.csv` for lynx).

**Primers CSV format** — columns:

```         
locus,primerF,primerR,type[,motif][,sequence]
```

- **type** is `microsat` (STR) or `SNP`.
- **motif** — the STR repeat unit, filled in for microsat loci.
- **sequence** — the reference sequence, filled in for SNP loci.

`motif` and `sequence` are each optional and used only for the marker type they belong to. The parser tolerates a UTF-8 BOM and trailing empty columns, and accepts `type` in upper or lower case.

### View, download, rename, delete

In the **Catalog** table each panel shows its code, species, and **marker count**. For each row: - **view** — expand it to see every marker (locus, type, forward/reverse primer, and motif-or-sequence). - **download** — get the original primers file back. - **rename** — edit the common/latin species names. - **delete** — remove the panel. Avoid deleting a panel that kits still reference.

------------------------------------------------------------------------

## 3. Kits

A **kit** ties a kit code to a panel (species), a set of tag columns, a negative-control rule, and the client(s) who own it. Clients pick a kit when submitting — they never configure any of this themselves. Open **Kits** from the top menu.

### Register one or many kits

Use the **Register kit(s)** form. You can create several kits at once that share the same configuration:

- **Kit code(s)** — one or more codes, separated by commas or spaces (e.g. `DIVJA240, DIVJA241, DIVJA242`). Each becomes its own kit.
- **Primer panel (species)** — choose from the panels you created in Section 2.
- **Tag columns** — tick the PP columns (PP1…PP12) this kit uses. These populate the client's tag picker at submission.
- **Negative control name pattern** — default `blank`. Any sample whose name contains this text is treated as a negative control by the analysis.
- **Assign to users** — type a client's email in the picker and select them; add as many as needed. Assigned clients see the kit in their **My kits**.
- **Description** — optional.

Click **Register kit(s)**. If some codes fail (e.g. a duplicate code), the page reports which ones so you can fix and retry just those.

### Edit or delete a kit

In the **All kits** table, click **edit** on a row to change its **status** and its **assigned users**, then **Save**. Use **delete** to remove a kit.

Reassigning is done here: add or remove users in the assignee picker while editing a row.

------------------------------------------------------------------------

## 4. Kit lifecycle and the reanalyse rule

Each kit moves through four statuses:

| Status | Set by | Meaning |
|------------------------|------------------------|------------------------|
| **sent** | admin | Kit registered / physical kit shipped. |
| **received** | client | Client confirmed the kit arrived (their **Mark received** button). |
| **analysed** | **automatic** | A genotyping job for this kit **succeeded**. The kit is now locked. |
| **reanalyse** | admin | You've re-opened an analysed kit so the client can submit it again. |

**Why kits lock:** a kit flips to **analysed** automatically the moment one of its jobs succeeds, and the client can't submit an analysed kit. This prevents accidental duplicate runs and duplicate billing.

**To let a client re-run a kit:** open **Kits**, **edit** the kit, set its status to **reanalyse**, and **Save**. The client can then submit it again.

------------------------------------------------------------------------

## 5. Users

Open **Users** from the top menu to see every account with its email, organisation, role, and active state. For any account other than your own you can:

- **Make admin / Demote** — grant or remove admin rights.
- **Activate / Deactivate** — enable or disable the account. Deactivated users can't use the app.

You **cannot change your own account** here (no self-demotion or self-deactivation) — ask another admin if needed.

> **Kit assignment is not done here** — assign kits to users on the **Kits** page ([Section 3](#3-kits)).

**New-user alerts:** whenever a client registers, all admins receive an email so you can assign them a kit. The signup email links straight to the **Users** page.

------------------------------------------------------------------------

## 6. Handling client issues

**A client's job failed.** Open the job (via the client's account or the job link in the failure email). The job page shows the error message. Common causes are bad/mismatched FASTQ files or sample sheets that don't match the data. Advise the client to check inputs and submit a new analysis.

**A client needs to re-run an analysed kit.** Set the kit to **reanalyse** on the **Kits** page — see [Section 4](#4-kit-lifecycle--the-reanalyse-rule).

**A client can't see their kit.** Confirm the kit exists and that the client's email is in the kit's assignee list (**Kits → edit**). Also confirm the account is **active** on the **Users** page.

**Wrong panel or tags on a kit.** Panel choice and tag columns are set at kit creation. If they're wrong, delete the kit and re-register it with the correct panel/tags (make sure the correct panel exists first).

**Low-read pauses.** If a client's job sits in **awaiting_confirmation**, that's the built-in low-read safety check — the client (not the admin) chooses **Run anyway** or **Cancel** on their job page. Reassure them it's expected when the FASTQ has fewer reads than the expected number they entered.

------------------------------------------------------------------------

## 7. Related documentation

- [User Guide](/manuals/user) — the client-facing flow.
- [`kit-onboarding.md`](https://github.com/divjalabs/STReamGT/blob/main/docs/kit-onboarding.md) — registering a kit via the API instead of the UI.
- [`architecture.md`](https://github.com/divjalabs/STReamGT/blob/main/docs/architecture.md) — how the platform is put together.
- [`aws-setup.md`](https://github.com/divjalabs/STReamGT/blob/main/docs/aws-setup.md), [`deployment.md`](https://github.com/divjalabs/STReamGT/blob/main/docs/deployment.md) — infrastructure & ops.

------------------------------------------------------------------------

*Questions about admin access? Contact the platform owner.*
