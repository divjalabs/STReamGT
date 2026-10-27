# Registering a kit (admin)

A **kit** is the stable mapping of a kit code to its primers, tag columns, controls and
species. Users pick a kit at submission; its files/settings are attached to every run.
Only admins can create kits.

## What you need
Reference files live in `STReam_primers_tags/`:
- a **primers CSV** for the species/panel, e.g. `UA_primers.csv` (bear), `LL_MPA_primers.csv`
  (lynx). Columns: `locus,primerF,primerR,type[,motif][,sequence]`. `motif` is the STR
  repeat unit; `sequence` is the SNP reference. `type` is `microsat` or `SNP`.
- the shared **tags CSV** `tags.csv` — wide `Position,PP1..PP12` layout.

## Steps
1. Upload both CSVs to S3 (or via the admin UI) and note their object keys.
2. `POST /api/kits` (admin token) with:
   ```json
   {
     "kit_code": "DIVJA240",
     "species": "bear",
     "primers_csv_key": "kits/DIVJA240/UA_primers.csv",
     "tags_csv_key": "kits/shared/tags.csv",
     "controls": [{"name_pattern": "blank", "kind": "negative"}],
     "primers":  [ ... ],          // optional: parsed rows for display/validation
     "tag_columns": [ ... ]         // e.g. PP1..PP12; used for the submit-page picker
   }
   ```
3. To pre-fill `primers` / `tag_columns` from the real files, `POST /api/kits/parse`
   (multipart: `primers_csv`, `tags_csv`) — it returns parsed structures you paste into
   the create call.

## Notes
- The **tags CSV is required in S3** — its positional TAG:TAG values can't be
  reconstructed from the DB. The primers CSV is optional in S3 (the worker can rebuild it
  from the stored `primers` rows), but storing it is recommended for fidelity.
- `controls[].name_pattern` maps to `parameters.json`'s `negative_name` (default `blank`):
  any sample whose name contains it is treated as a negative control by the allele caller.
