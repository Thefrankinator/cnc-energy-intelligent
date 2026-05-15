# Bronze Layer — Recap
**Date**: 2026-05-15 | **Script**: `src/bronze/ingest.py` | **Status**: Done

---

## What the Bronze Layer Does

Principle: touch nothing. Copy the 19 source CSV files verbatim, hash them, log everything, version with DVC. The Bronze layer is the permanent, immutable snapshot of the raw data.

---

## Run History (from `ingestion_log.jsonl`)

| Run | run_id | Started | Copied | Skipped | Duration |
|---|---|---|---|---|---|
| 1 | `a2402b7f...` | 2026-05-15 11:40:04 UTC | 19 | 0 | 1.05s |
| 2 | `02728551...` | 2026-05-15 11:43:08 UTC | 0 | 19 | 0.17s |
| 3 | `c974a5b1...` | 2026-05-15 16:02:20 UTC | 0 | 19 | 0.33s |

- **Run 1**: Initial ingestion — all 19 files copied and verified
- **Run 2**: Idempotency test — all files unchanged, nothing copied
- **Run 3**: Post DVC install — same result, idempotency confirmed

---

## Files Ingested

### `data/bronze/metadata/`

| File | Lines | Size | MD5 |
|---|---|---|---|
| train.csv | 19 | 547 B | `5616823a...` |

### `data/bronze/experiments/`

| File | Lines | Size | MD5 |
|---|---|---|---|
| experiment_01.csv | 1,056 | 467,193 B | `ec446ebd...` |
| experiment_02.csv | 1,669 | 736,459 B | `d5eeb793...` |
| experiment_03.csv | 1,522 | 671,985 B | `564d87ac...` |
| experiment_04.csv | 533 | 234,196 B | `2002b1d6...` |
| experiment_05.csv | 463 | 202,320 B | `5d6baa0f...` |
| experiment_06.csv | 1,297 | 574,296 B | `89454311...` |
| experiment_07.csv | 566 | 250,860 B | `bf87dc61...` |
| experiment_08.csv | 606 | 267,820 B | `3bd7306e...` |
| experiment_09.csv | 741 | 328,887 B | `9d2accc6...` |
| experiment_10.csv | 1,302 | 574,595 B | `693d3b84...` |
| experiment_11.csv | 2,315 | 1,022,545 B | `e597fe0d...` |
| experiment_12.csv | 2,277 | 1,004,981 B | `c446004a...` |
| experiment_13.csv | 2,234 | 987,653 B | `ca36136b...` |
| experiment_14.csv | 2,333 | 1,030,795 B | `e4291409...` |
| experiment_15.csv | 1,382 | 608,883 B | `3df79bab...` |
| experiment_16.csv | 603 | 264,491 B | `8cddf382...` |
| experiment_17.csv | 2,151 | 948,848 B | `4970660c...` |
| experiment_18.csv | 2,254 | 996,061 B | `40e3d00d...` |

**Total: 25,286 data rows across 18 experiments** (excluding headers)

---

## How Idempotency Works

On every run, the script:
1. Calculates the MD5 hash of each source file
2. Compares it against the last run's hashes in `ingestion_log.jsonl`
3. Skips any file whose hash is identical — no copy, no overwrite
4. Only copies files that are new or changed

This means running the script 10 times on the same data produces the same Bronze output as running it once.

---

## Integrity Check

After each copy, the script re-hashes the destination file and compares it to the source hash. If they differ, the pipeline exits with an error. This guarantees bit-for-bit fidelity between source and Bronze.

---

## Output Structure

```
data/bronze/
├── metadata/
│   └── train.csv                  -- verbatim copy, immutable
├── experiments/
│   ├── experiment_01.csv
│   ├── experiment_02.csv
│   └── ... (up to 18)
└── ingestion_log.jsonl            -- append-only, one JSON line per run
```

---

## DVC Versioning

DVC was initialized on 2026-05-15. `dvc add data/bronze` was run manually after the first ingestion to create `data/bronze.dvc` (the DVC pointer file tracked by Git).

Remaining: configure a shared DVC remote so teammates can pull the data.
```bash
dvc remote add -d team_remote /path/to/shared/store
dvc push
```

---

## Key Rules

- A Bronze file is never modified after ingestion — any change is a bug
- `ingestion_log.jsonl` is append-only — never delete entries
- Every run has a unique `run_id` (UUID) for traceability
