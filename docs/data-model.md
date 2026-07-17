# STReamGT — Data model

Entity–relationship diagram of the backend database (SQLAlchemy models in `backend/app/models/`). Render this on GitHub, in an IDE Mermaid preview, or at <https://mermaid.live>.

``` mermaid
erDiagram
    users ||--o{ jobs          : "submits"
    users ||--o{ kits          : "creates (created_by)"
    users }o--o{ kits          : "kit_access (assigned to)"
    primer_panels ||--o{ primers : "contains"
    primer_panels ||--o{ kits    : "chosen by"
    tag_layouts  ||..o{ tag_columns : "columns picked from (no FK)"
    kits ||--o{ tag_columns    : "has selected"
    kits ||--o{ controls       : "has"
    kits ||--o{ jobs           : "genotyped in"
    jobs ||--o{ sample_batches : "has"
    jobs ||--o{ result_files   : "produces"

    users {
        int      id PK
        string   email UK
        string   password_hash
        string   organisation
        enum     role "user | admin"
        bool     is_active
        datetime subscription_expires
        datetime created_at
    }

    primer_panels {
        int      id PK
        string   code UK
        string   species_common
        string   species_latin
        string   description
        string   primers_csv_key "S3"
        datetime created_at
    }

    primers {
        int    id PK
        int    panel_id FK
        string locus
        enum   type "microsat | snp"
        string primer_f
        string primer_r
        string motif "STR loci"
        string sequence "SNP loci"
    }

    tag_layouts {
        int    id PK
        string name "default"
        string tags_csv_key "S3"
        json   column_names "[PP1..PP12]"
    }

    kits {
        int      id PK
        string   kit_code UK
        int      panel_id FK
        string   species "denormalized"
        string   description
        enum     status "sent|received|analysed|reanalyse"
        string   primers_csv_key "S3 (denormalized)"
        string   tags_csv_key "S3 (denormalized)"
        int      created_by FK
        datetime created_at
    }

    tag_columns {
        int    id PK
        int    kit_id FK
        string name "PP1..PP12"
        int    ordinal
    }

    controls {
        int    id PK
        int    kit_id FK
        string name_pattern "e.g. blank"
        enum   kind "negative | positive"
    }

    kit_access {
        int kit_id PK,FK
        int user_id PK,FK
    }

    jobs {
        int      id PK
        string   public_id UK
        int      user_id FK
        int      kit_id FK
        enum     status "queued..succeeded|failed"
        enum     fastq_source "upload|server|link"
        string   fastq1_ref "S3 key / path / URL"
        string   fastq2_ref
        float    min_identity
        int      min_overlap
        bigint   expected_read_number
        bigint   observed_read_count
        bool     reads_confirmed
        string   storage_prefix
        string   nextflow_run_name
        string   error_message
        datetime created_at
        datetime started_at
        datetime finished_at
    }

    sample_batches {
        int    id PK
        int    job_id FK
        int    ordinal
        string name "e.g. HRM01"
        string sample_sheet_key "S3 xlsx"
        string sample_names_text "pasted"
        string species "defaults to kit"
        json   selected_tags "[PP1..PP4]"
    }

    result_files {
        int      id PK
        int      job_id FK
        enum     kind "genotypes|html_report|..."
        string   object_key "S3"
        string   filename
        bigint   size_bytes
        datetime created_at
    }
```

## Relationships in words

- **users → jobs** (1:N): a user submits many genotyping jobs (`jobs.user_id`).
- **users → kits** (1:N): the admin who registered a kit (`kits.created_by`, optional).
- **users ↔ kits** (M:N): the `kit_access` junction table controls which non-admin users can see/use a kit. Admins see all kits regardless.
- **primer_panels → primers** (1:N): a panel owns its locus rows (cascade delete).
- **primer_panels → kits** (1:N): a kit references one panel (`kits.panel_id`, optional); species + `primers_csv_key` are **denormalized** onto the kit at save time.
- **tag_layouts**: a single shared row (PP1..PP12). It is *not* linked by a foreign key — a kit's `tag_columns` are a chosen subset of these column names.
- **kits → tag_columns / controls** (1:N, cascade): the PP columns selected for the kit and its control-name patterns.
- **kits → jobs** (1:N): every job runs against exactly one kit (`jobs.kit_id`).
- **jobs → sample_batches** (1:N, cascade): each batch = one sample sheet + a subset of the kit's tag columns; becomes one row of the generated `input.tsv`.
- **jobs → result_files** (1:N, cascade): output artifacts (stored in S3), one row per file.

## Notes

- **Cascade deletes:** deleting a panel removes its primers; deleting a kit removes its tag_columns, controls, and kit_access rows; deleting a job removes its sample_batches and result_files.
- **S3, not the DB:** large data (FASTQ, sample sheets, primer/tag CSVs, results) live in S3; the DB stores only object keys/paths (`*_key`, `*_ref`, `object_key`).
- **Enums:** `role`, `status` (kit + job), `fastq_source`, `primer type`, `control kind`, and `result kind` are defined in `backend/app/models/enums.py`.
