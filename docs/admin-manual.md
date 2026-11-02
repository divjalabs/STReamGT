---

editor_options: 
  markdown: 
    wrap: 72
---

# STReamGT — Admin Guide

*For STReamGT administrators.*

This guide covers the admin-only features of the STReamGT web app: managing primer panels, registering kits, managing users, and handling client issues. It assumes you're already familiar with the client-facing flow — if not, read the [User Guide](/manuals/user) first, since admins can do everything a client can, plus the extra screens described here.

> **Scope:** this document is about the **web app admin UI** only. For the API-level way to onboard a kit (tokens, `POST /api/kits`, file keys), see [`kit-onboarding.md`](https://github.com/divjalabs/STReamGT/blob/main/docs/kit-onboarding.md). For infrastructure, deployment, and AWS operations, see [`aws-setup.md`](https://github.com/divjalabs/STReamGT/blob/main/docs/aws-setup.md) and [`deployment.md`](https://github.com/divjalabs/STReamGT/blob/main/docs/deployment.md).

------------------------------------------------------------------------

## 1. The admin role

Admins see three extra items in the top menu — **Kits**, **Panels**, and **Users** — alongside the normal *My jobs · My kits · New analysis*.

You become an admin only by being **promoted by another admin** on the **Users** page (see [Section 5](#5-users)).

**Typical admin workflow for onboarding a client:** 1. Make sure a **primer panel** exists for the species → [Section 2](#2-primer-panels). 2. **Register a kit** (or several) and ship each one with its **claim code** sticker → [Section 3](#3-kits). 3. The client redeems the code, marks the kit received, submits an analysis, and downloads results. 4. When they need to re-run an already-analysed kit, flip it to **reanalyse** → [Section 4](#4-kit-lifecycle--the-reanalyse-rule).

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

A **kit** ties a kit code to a panel (species), a set of tag columns and a negative-control rule. A kit reaches a client when they redeem the claim code shipped in its box; clients pick a kit when submitting and never configure any of this themselves. Open **Kits** from the top menu.

### Register one or many kits

Use the **Register kit(s)** form. Every kit in one batch shares the same configuration, and there are two ways to name them:

- **Generate codes** (the usual way) — say how many kits you need, and the platform names them after the panel and today's date: `Bearplex_261029_01`, `_02`, and so on. Numbering restarts each day for each panel, and a second batch the same day continues from where the first stopped.
- **Enter my own** — type codes by hand, separated by commas or spaces. Use this when a code has to match an external numbering scheme.

Because the code comes from the panel's name, **name your panels the way you want kits to read** — Section 2 → **rename**, which edits the panel code as well as the species labels. A panel code may use letters, digits, `.`, `-` and `_` only, because it ends up in kit codes, control well names and file paths. If three wolf panels should produce distinguishable kits, give the three panels distinct names. Renaming a panel later never changes codes already issued — those are printed on stickers.

Then:

- **Primer panel (species)** — choose from the panels you created in Section 2.
- **Tag columns** — tick the PP columns (PP1…PP12) this kit uses. These populate the client's tag picker at submission.
- **Negative control name pattern** — default `blank`. Any sample whose name contains this text is treated as a negative control by the analysis.
- **Control positions** — collapsed by default; the heading says how many wells are selected. Open it to paint control wells onto a 96-well plate, and to work with saved layouts: pick a **Saved template** and **Apply** it, **Save positions as template** to keep the current layout for next time, or **Delete** a template you no longer use. Deleting a template leaves kits already registered untouched — their wells were copied onto them at registration.
- **Description** — optional.

There is no "assign to users" step: a kit reaches whoever redeems its claim code.

Click **Register kit(s)**. A generated batch is all-or-nothing: if anything is rejected, no kits are created, so the codes you print always match what exists. (Typing codes by hand still reports individual failures, since each is registered separately.)

### The claim codes, and the sticker sheet

After registering, the page shows each kit's **claim code** — the code whoever receives the kit types in to unlock it. **⭳ Download for printing** gives you a spreadsheet with one row per kit: kit code, claim code, species, panel, the date, and an empty **Sent to** column for whoever packs the boxes.

That sheet covers exactly the kits you just registered. If you lose it, or close the page before downloading, open **Kits** and use **⭳ Sticker sheet (.xlsx)** — it reprints the codes of every kit nobody has claimed yet. The codes are stored encrypted, so reprinting gives you the same ones; the stored copy is destroyed the moment a kit is claimed, at which point the code can do nothing anyway.

Two things are *not* reprintable: a kit someone has already claimed, and a kit registered before October 2026 (codes were kept as fingerprints only until then). For either, find the row in **Kits** and click **code** to issue a new one — the old code stops working immediately, so the kit needs a new sticker.

### Finding a kit, and exporting the list

Every column in **All kits** sorts — click a heading, click again to reverse.

**⭳ Export kits (.xlsx)** downloads the whole list as a spreadsheet, with a filter row ready for
sorting and filtering in Excel. It deliberately contains no claim codes — this is the file that
gets emailed around, and an unclaimed code is enough to take a kit. Codes come only from
**⭳ Sticker sheet (.xlsx)**, the file the lab prints.

### Edit or delete a kit

In the **All kits** table, click **edit** on a row to change its **status** and its **assigned users**, then **Save**. Use **delete** to remove a kit.

Kits reach people by claim code, which is why the table shows **Claimed by** and why the register form has no assignee field. The picker here is the exception that remains: use it to give someone access to a kit they did not claim — most often a kit claimed by the wrong account.

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

**Claim codes and the platform's keys.** A kit's claim code is stored twice and never as plain
text: as a fingerprint, which is what redeeming checks against, and encrypted, which is what
**⭳ Sticker sheet** reprints. The encrypted copy is deleted as soon as the kit is claimed. Both
use a key kept separate from the one that signs logins and held in AWS Parameter Store rather than
the database — so a security rotation of the login key cannot invalidate codes on kits already in
the post, and a stolen database backup contains no usable codes.

**Clients can now stop their own runs.** A user who spots a mistake can press **Stop analysis** on
the job page; the run halts and the kit stays unlocked, so they can resubmit without asking you.
That only applies *before* an analysis finishes — a kit that reached **analysed** still needs you
to set **reanalyse**.

**A dead analysis no longer blocks a kit.** If the machine running a job disappears, the platform
notices when anyone opens the job or the kits page and marks it failed with the reason, freeing the
kit. The `scripts/force-fail-job.sh` script remains only as a last resort.

------------------------------------------------------------------------

## 5. Users

Open **Users** from the top menu to see every account with its email, organisation, role, and active state. For any account other than your own you can:

- **Make admin / Demote** — grant or remove admin rights.
- **Activate / Deactivate** — enable or disable the account. Deactivated users can't use the app: the block takes effect on their very next click, not at their next login.
- **Delete** — remove the account permanently.

**Deactivate or delete?** Deactivate is almost always the right one. It stops access immediately and keeps every record attached to a real person, so you can still say who submitted which analysis. Delete exists to tidy away an account that never did anything — an abandoned sign-up, or a test account.

**Delete refuses rather than destroying work.** If the account has submitted an analysis, owns a project, claimed or registered a kit, uploaded reads, saved a control template, started a matching run or hand-edited a genotype, you get a message naming what is in the way — for example *"Cannot delete bob@lab.org: it has 3 analyses, 1 project. Deactivate the account instead."* Nothing is deleted in that case. The one thing deletion does take with it is the account's kit access, which is the point: a kit someone was given access to but never claimed is unaffected, it simply stops being theirs.

If a client account is blocked only by a **claimed kit** and you genuinely want it gone, the claim has to be released first. There is no button for this yet — it is `DELETE /api/kits/{kit_id}/claim`, which detaches the claimer and leaves the printed claim code working, so the kit can be claimed again by the right person.

You **cannot change or delete your own account** here, and the **last remaining admin** cannot be demoted, deactivated or deleted by anyone — otherwise nobody would be able to reach these screens again. Ask another admin if you need your own account changed.

> **Kits are not handed out here** — clients claim them with the code in the box ([Section 3](#3-kits)), and the **Kits** page can grant access by hand if one goes to the wrong account.

**New-user alerts:** whenever a client registers, all admins receive an email. The signup email links straight to the **Users** page.

------------------------------------------------------------------------

## 6. Handling client issues

**A client's job failed.** Open the job (via the client's account or the job link in the failure email). The job page shows the error message. Common causes are bad/mismatched FASTQ files or sample sheets that don't match the data. Advise the client to check inputs and submit a new analysis.

**A client needs to re-run an analysed kit.** Set the kit to **reanalyse** on the **Kits** page — see [Section 4](#4-kit-lifecycle--the-reanalyse-rule).

**A client can't see their kit.** Confirm the kit exists and that they redeemed its claim code — the **Claimed by** column on the **Kits** page shows who holds it. If it was claimed by the wrong account, **Kits → edit** can grant the right person access. Also confirm the account is **active** on the **Users** page.

**A client never gets their password-reset email.** The reset page tells them whether the address is registered, so a typo says so immediately. If it says a link was sent and nothing arrives, ask them to check their spam folder first: the platform sends from `elena.pazhenkova@divjalabs.com` through Amazon SES, and until the `divjalabs.com` DNS carries SES's DKIM records plus `include:amazonses.com` in its SPF, that mail is unauthenticated and some providers will filter it. A genuine send failure is logged in CloudWatch (`/aws/lambda/streamgt-api`, search for "password-reset email failed"); nothing in the log means it was accepted for delivery and the problem is at the receiving end.

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
