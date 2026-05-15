# CNC Energy Intelligent — DataOps Pipeline

Medallion data pipeline (Bronze → Silver → Gold) for CNC milling energy data.  
Dataset: CNC Milling, University of Michigan SMART Lab (2018) — 18 experiments.

---

## Architecture

```
dataset/  (19 CSV source files)
    │
    ▼
 BRONZE  — Immutable copy, MD5 integrity check, idempotent ingestion, DVC-versioned
    │
    ▼
 SILVER  — Schema validation, defect flagging (3 rules), timestamp injection,
           NaN handling, quality report per run
    │
    ▼
  GOLD   — Feature store: 121 features + 2 targets, train/val/test split
```

| Layer | Format | Rows | Columns |
|-------|--------|------|---------|
| Bronze | CSV (unchanged) | 25,286 source rows across 18 experiments | 48 sensor cols |
| Silver | Parquet | same | 48 + 6 quality flags = 54 cols |
| Gold | Parquet | 17,315 (after defect removal) | 121 features + 2 targets |

**Split:** Exp 01–14 → train (12,398 rows) · Exp 15–16 → validation (1,042) · Exp 17–18 → test (3,875, held-out)

---

## Pipeline stages (`dvc.yaml`)

| Stage | Script | Input → Output |
|-------|--------|----------------|
| `ingest` | `src/bronze/ingest.py` | `dataset/` → `data/bronze/` |
| `clean` | `src/silver/transform.py` | `data/bronze/` → `data/silver/` |
| `featurize` | `src/gold/build.py` | `data/silver/` → `data/gold/` |

---

## Setup

```bash
git clone https://github.com/Thefrankinator/cnc-energy-intelligent.git
cd cnc-energy-intelligent

python -m venv .venv
source .venv/bin/activate        # Linux/macOS
.venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

---

## Run the full pipeline

```bash
# Reproduce all three stages: ingest → clean → featurize
dvc repro

# Pull already-computed data from the shared Google Drive remote
dvc pull

# Check which stages are out of date
dvc status
```

Each stage is **idempotent** — re-running skips unchanged outputs automatically.  
To force a full re-run, delete the relevant `data/<layer>/` folder and run `dvc repro` again.

---

## Docs

- `dataops_pipeline.md` — full pipeline design with progress tracking
- `dataset_info.md` — dataset columns, axes, and sensor descriptions
- `data/bronze/bronze_recap.md` — Bronze layer ingestion summary
- `data/silver/quality/quality_report_analysis.md` — Silver quality report analysis
- `data/gold/gold_recap.md` — Gold feature engineering details
